"""Inclusive current physical-deck counts, using one isolated native Battlecry."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CheckDeckCondition,
    ChoicePurpose, CostSpec, DeckCondition, DeckCostCondition, DeckCostCeilingCondition,
    DeckCostDiversityCondition, DeckCountCondition, DeckMinionCostCondition,
    DeckMinionCostSumCondition, DeckSpellSchoolCondition, DeckSpec, Game, MatchSetup,
    OpeningHook, PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice,
    SnapshotError, SpellSchool, UnknownDeckFacts,
    matches_deck_condition)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, Draw,
    GainArmor, InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'JAIL_456'
LOW = DeckCountCondition(10, 'at_most')
HIGH = DeckCountCondition(25, 'at_least')
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/current-deck-count-basics.json'
PIN = '4d48d2cfa503e46f5ee68686a6a88778f90e4dd411986fb335e3ad777bc2add2'


def evidence():
    value = json.loads(SUPPORT.read_bytes())
    if canonical_digest(value) != PIN or [r['id'] for r in value['records']] != ['BAR_916', NATIVE]:
        raise ValueError('Complete current deck-count evidence changed')
    for row in value['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete raw source changed')
    return {r['id']: r['data'] for r in value['records']}


def pause(player):
    return RequestChoice(player, (ChoiceOption('ok', 'Continue', ()),))


def branch(player, condition):
    return CheckDeckCondition(player, condition, (GainArmor(player, 3),), (GainArmor(player, 1),))


def registry():
    r = opening_registry()
    raw = evidence()
    r.register_behavior('count.nop', lambda c: ())
    for i in range(1, 71):
        r.register_card(CardDefinition(f'count.fill.{i}', 'Experimental physical deck slot',
            CardType.MINION, cost=1, health=2, metadata=metadata()))
    for cid, kind, fields in (
        ('count.spell', CardType.SPELL, {}),
        ('count.weapon', CardType.WEAPON, {'attack': 1, 'durability': 1}),
        ('count.location', CardType.LOCATION, {'durability': 1, 'on_use': 'count.nop'}),
        ('count.hero', CardType.HERO, {'health': 30, 'hero_card': True,
            'initial_hero_power': 'mage.power', 'on_play': 'count.nop'}),
    ):
        r.register_card(CardDefinition(cid, cid, kind,
            metadata=metadata(CardClass.MAGE if kind == CardType.HERO else CardClass.NEUTRAL), **fields))
    r.register_card(CardDefinition('count.no_meta', 'Known definition without class metadata',
        CardType.MINION, health=1))
    r.register_behavior('count.native', lambda c: (CheckDeckCondition(c.player_id, HIGH, (Draw(c.player_id),)),))
    card = raw[NATIVE]
    r.register_card(CardDefinition(NATIVE, card['name'], CardType.MINION, cost=card['cost'],
        attack=card['attack'], health=card['health'], battlecry='count.native', metadata=metadata_from_record(card)))

    def prepare(c):
        return (ChangeManaCrystals(c.player_id, 9), AddToHand(c.player_id, NATIVE))
    r.register_behavior('count.prepare', prepare)
    r.register_card(CardDefinition('count.fixture.prepare', 'Experimental opening preparation',
        CardType.MINION, health=1, metadata=metadata(),
        opening_hooks=(OpeningHook('after_mulligan', 'count.prepare'),)))

    def fail(c):
        raise ResolutionError('Expected late current-count branch failure')
    r.register_behavior('count.fail', fail)
    first = lambda c: c.state.entities[c.state.players[c.player_id].deck[0]]
    scripts = {
        'count.draw': lambda c: (Draw(c.player_id),),
        'count.add': lambda c: (AddToDeck(c.player_id, 'count.fill.70'),),
        'count.clear': lambda c: (DestroyDeckMatching(c.player_id, count=70, reveal=False),),
        'count.local': lambda c: (ModifyCost(first(c).id, CostSpec(set_to=20), c.source_id),),
        'count.face': lambda c: (TransformCapturedMinion(CardReference.capture(first(c)), 'count.fill.70'),),
    }
    for label, condition, before in (
        ('low', LOW, lambda c: Draw(c.player_id)),
        ('high', HIGH, lambda c: AddToDeck(c.player_id, 'count.fill.70')),
    ):
        scripts['count.check.' + label] = lambda c, q=condition: (branch(c.player_id, q),)
        scripts['count.before.' + label] = lambda c, q=condition, change=before: (pause(c.player_id), change(c), branch(c.player_id, q))
        yes_change = (lambda c: AddToDeck(c.player_id, 'count.fill.70')) if label == 'low' else (lambda c: Draw(c.player_id))
        no_change = (lambda c: Draw(c.player_id)) if label == 'low' else (lambda c: AddToDeck(c.player_id, 'count.fill.70'))
        scripts['count.selected.' + label] = lambda c, q=condition, y=yes_change, n=no_change: (CheckDeckCondition(c.player_id, q,
            (pause(c.player_id), y(c), GainArmor(c.player_id, 3)),
            (pause(c.player_id), n(c), GainArmor(c.player_id, 1))),)
        scripts['count.fail.' + label] = lambda c, q=condition: (branch(c.player_id, q), InvokeBehavior('count.fail', c.source_id, c.player_id))
        scripts['count.wait.fail.' + label] = lambda c, q=condition: (pause(c.player_id), branch(c.player_id, q), InvokeBehavior('count.fail', c.source_id, c.player_id))
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata(CardClass.MAGE)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class CurrentDeckCountTests(unittest.TestCase):
    def game(self, count=0, hand=(), *, other_count=0, other_hand=(), active=1, deck=None):
        own = tuple(f'count.fill.{i}' for i in range(1, count + 1)) if deck is None else tuple(deck)
        other = tuple(f'count.fill.{i}' for i in range(1, other_count + 1))
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, deck=own, hero_power_card_id='mage.power', mana=10, max_mana=10),
            PlayerSetup('warrior.hero', hand=other_hand, deck=other, hero_power_card_id='warrior.power', mana=10, max_mana=10)),
            active_player=active, seed=85), registry())

    def query(self, g, condition=LOW, player=1):
        return matches_deck_condition(g.state, g.registry, player, condition)

    def play(self, g, cid):
        player = g.state.active_player
        identity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, identity))
        return identity

    def choose(self, g):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, () if q.purpose == ChoicePurpose.MULLIGAN else ('ok',)))

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def portable(self, g):
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

    def resume(self, g):
        restored, cloned = self.portable(g), g.clone()
        self.choose(g)
        for other in (restored, cloned):
            self.choose(other)
            self.assertEqual(other.snapshot(), g.snapshot())
        self.portable(g)

    def test_complete_raw_pins_native_identity_and_unadapted_targeted_source(self):
        raw = evidence()
        card = registry().card(NATIVE)
        self.assertEqual((card.cost, card.attack, card.health, card.metadata.classes, card.metadata.rarity, card.metadata.tribes),
            (2, 2, 3, (CardClass.NEUTRAL,), Rarity.COMMON, ('mech',)))
        self.assertEqual(card.metadata, metadata_from_record(raw[NATIVE]))
        self.assertIn('25 or more cards', raw[NATIVE]['text_en'])
        self.assertIn('10 or fewer', raw['BAR_916']['text_en'])
        self.assertIn('to a minion', raw['BAR_916']['text_en'])
        self.assertEqual(raw['BAR_916']['tags']['LIFESTEAL'], 1)
        with self.assertRaises(UnsupportedDefinitionError):
            registry().card('BAR_916')

    def test_at_most_includes_exact_threshold_and_excludes_next_slot(self):
        for count in (0, 1, 9, 10, 11, 25, 70):
            with self.subTest(count=count):
                self.assertEqual(self.query(self.game(count)), count <= 10)

    def test_at_least_includes_exact_threshold_and_excludes_previous_slot(self):
        for count in (0, 10, 24, 25, 26, 70):
            with self.subTest(count=count):
                self.assertEqual(self.query(self.game(count), HIGH), count >= 25)

    def test_zero_operands_and_empty_deck_are_inclusive(self):
        for count in (0, 1):
            g = self.game(count)
            self.assertEqual(self.query(g, DeckCountCondition(0, 'at_most')), count == 0)
            self.assertTrue(self.query(g, DeckCountCondition(0, 'at_least')))

    def test_every_card_kind_and_duplicate_physical_slot_counts(self):
        deck = ('count.spell', 'count.weapon', 'count.location', 'count.hero') + ('count.fill.1',) * 7
        g = self.game(deck=deck)
        self.assertEqual(len(g.state.players[1].deck), 11)
        self.assertFalse(self.query(g))
        self.assertTrue(self.query(g, DeckCountCondition(11, 'at_least')))
        self.assertTrue(self.query(g, DeckCountCondition(11, 'at_most')))
        self.portable(g)

    def test_pure_structural_query_needs_no_definition_or_class_metadata(self):
        g = self.game(deck=('count.no_meta',) * 11)
        self.assertFalse(matches_deck_condition(g.state, object(), 1, LOW))
        self.assertTrue(matches_deck_condition(g.state, object(), 1, DeckCountCondition(11, 'at_least')))
        self.portable(g)

    def test_scenario_current_query_requires_no_original_constructed_facts(self):
        g = self.game(25)
        self.assertIsNone(g.state.opening)
        self.assertTrue(self.query(g, HIGH))
        with self.assertRaises(UnknownDeckFacts):
            matches_deck_condition(g.state, g.registry, 1, DeckCondition('starting'))

    def test_query_is_player_local_and_independent_of_active_player(self):
        g = self.game(10, other_count=25, active=2)
        self.assertTrue(self.query(g, LOW, 1))
        self.assertFalse(self.query(g, LOW, 2))
        self.assertFalse(self.query(g, HIGH, 1))
        self.assertTrue(self.query(g, HIGH, 2))

    def test_draw_add_and_clear_recompute_current_quantity(self):
        g = self.game(11, ('count.draw', 'count.add', 'count.clear'))
        self.assertFalse(self.query(g))
        self.play(g, 'count.draw')
        self.assertTrue(self.query(g))
        self.play(g, 'count.add')
        self.assertFalse(self.query(g))
        self.play(g, 'count.clear')
        self.assertTrue(self.query(g, DeckCountCondition(0, 'at_most')))
        self.portable(g)

    def test_face_and_local_cost_changes_do_not_change_physical_quantity(self):
        g = self.game(11, ('count.local', 'count.face'))
        identities = tuple(g.state.players[1].deck)
        self.play(g, 'count.local')
        self.assertFalse(self.query(g))
        self.play(g, 'count.face')
        self.assertEqual(tuple(g.state.players[1].deck), identities)
        self.assertFalse(self.query(g))
        self.portable(g)

    def test_ordinary_check_executes_match_or_miss_for_both_comparators(self):
        for label, count, expected in (('low', 10, 3), ('low', 11, 1), ('high', 25, 3), ('high', 24, 1)):
            with self.subTest(label=label, count=count):
                g = self.game(count, ('count.check.' + label,))
                self.play(g, 'count.check.' + label)
                self.assertEqual(self.armor(g), expected)
                self.assertEqual(len(g.state.players[1].deck), count)

    def test_unexecuted_low_gate_reads_quantity_after_choice_and_draw(self):
        for count in (11, 12):
            g = self.game(count, ('count.before.low',))
            self.play(g, 'count.before.low')
            self.assertFalse(self.query(g))
            self.resume(g)
            self.assertEqual(len(g.state.players[1].deck), count - 1)
            self.assertEqual(self.armor(g), 3 if count == 11 else 1)

    def test_unexecuted_high_gate_reads_quantity_after_choice_and_add(self):
        for count in (23, 24):
            g = self.game(count, ('count.before.high',))
            self.play(g, 'count.before.high')
            self.assertFalse(self.query(g, HIGH))
            self.resume(g)
            self.assertEqual(len(g.state.players[1].deck), count + 1)
            self.assertEqual(self.armor(g), 3 if count == 24 else 1)

    def test_selected_low_match_remains_selected_after_quantity_flips(self):
        g = self.game(10, ('count.selected.low',))
        self.play(g, 'count.selected.low')
        self.resume(g)
        self.assertFalse(self.query(g))
        self.assertEqual(self.armor(g), 3)

    def test_selected_low_miss_remains_selected_after_quantity_flips(self):
        g = self.game(11, ('count.selected.low',))
        self.play(g, 'count.selected.low')
        self.resume(g)
        self.assertTrue(self.query(g))
        self.assertEqual(self.armor(g), 1)

    def test_selected_high_match_remains_selected_after_quantity_flips(self):
        g = self.game(25, ('count.selected.high',))
        self.play(g, 'count.selected.high')
        self.resume(g)
        self.assertFalse(self.query(g, HIGH))
        self.assertEqual(self.armor(g), 3)

    def test_selected_high_miss_remains_selected_after_quantity_flips(self):
        g = self.game(24, ('count.selected.high',))
        self.play(g, 'count.selected.high')
        self.resume(g)
        self.assertTrue(self.query(g, HIGH))
        self.assertEqual(self.armor(g), 1)

    def test_late_action_and_choice_failures_roll_back_count_branch_and_history(self):
        for label, count in (('low', 10), ('low', 11), ('high', 24), ('high', 25)):
            for waiting in (False, True):
                cid = ('count.wait.fail.' if waiting else 'count.fail.') + label
                g = self.game(count, (cid,))
                if waiting:
                    self.play(g, cid)
                before = g.snapshot()
                with self.assertRaises(ResolutionError):
                    self.choose(g) if waiting else self.play(g, cid)
                self.assertEqual(g.snapshot(), before)

    def test_declaration_requires_strict_nonnegative_count_current_and_explicit_comparator(self):
        for value in (-1, True, 1.0, '10', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                DeckCountCondition(value, 'at_most')
        for comparison in ('less', 'greater', 'equal', '', True, None):
            with self.subTest(comparison=comparison), self.assertRaises(ValueError):
                DeckCountCondition(10, comparison)
        for scope in ('starting', 'hand', '', True, None):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                DeckCountCondition(10, 'at_most', scope)

    def test_typed_three_field_count_and_all_seven_old_conditions_roundtrip(self):
        g = self.game()
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        declarations = (LOW, HIGH, DeckCondition(), DeckCostCondition(4, 'local'),
            DeckSpellSchoolCondition(SpellSchool.SHADOW), DeckMinionCostCondition(4, 'less', 'local'),
            DeckCostCeilingCondition(3, 'printed'), DeckMinionCostSumCondition(100, 'printed'), DeckCostDiversityCondition(10, 'printed'))
        for declaration in declarations:
            wire = codec.encode(declaration)
            self.assertEqual(codec.decode(wire), declaration)
        self.assertEqual(set(codec.encode(LOW)['fields']), {'card_count', 'comparison', 'scope'})
        self.assertEqual(set(codec.encode(branch(1, LOW))['fields']), {'player_id', 'condition', 'on_match', 'on_miss'})
        for field in ('card_count', 'comparison', 'scope'):
            wire = codec.encode(LOW)
            del wire['fields'][field]
            with self.assertRaises(ValueError):
                codec.decode(wire)

    def test_rehashed_pending_invalid_count_comparison_scope_or_extra_field_rejects(self):
        g = self.game(11, ('count.before.low',))
        self.play(g, 'count.before.low')
        for field, value in (('card_count', True), ('card_count', -1), ('card_count', 10.0),
                             ('scope', 'starting'), ('comparison', 'greater'), ('invented', 1)):
            saved = deepcopy(g.snapshot())
            self.nested(saved['resolution_frame'], 'DeckCountCondition')['fields'][field] = value
            self.reject(saved)

    def test_player_validation_and_unknown_definitions_still_reject_natively(self):
        g = self.game(1)
        for player in (True, 0, 3, '1'):
            with self.subTest(player=player), self.assertRaises(ValueError):
                self.query(g, LOW, player)
        saved = g.snapshot()
        identity = g.state.players[1].deck[0]
        saved['state']['entities'][str(identity)]['card_id'] = 'unknown.count.face'
        self.reject(saved)

    def test_public_count_is_visible_but_private_condition_and_deck_faces_are_hidden(self):
        g = self.game(25, ('count.before.high',))
        self.play(g, 'count.before.high')
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player)) + json.dumps(g.for_player(player).legal_actions())
            self.assertIn('deck_count', text)
            for value in ('DeckCountCondition', 'card_count', 'on_match', 'on_miss', 'count.fill.25', 'resolution_frame', 'original_deck'):
                self.assertNotIn(value, text)
        self.portable(g)

    def test_native_24_25_26_boundary_draws_once_and_pays_once(self):
        for count in (24, 25, 26):
            with self.subTest(count=count):
                g = self.game(count, (NATIVE,))
                identity = self.play(g, NATIVE)
                self.assertEqual(len(g.state.players[1].deck), count - (count >= 25))
                self.assertEqual(len(g.state.players[1].hand), int(count >= 25))
                self.assertEqual(g.state.players[1].mana, 8)
                self.assertEqual(len(g.state.play_history), 1)
                self.assertIn(identity, g.state.players[1].board)
                self.assertEqual((g.state.entities[identity].attack, g.state.entities[identity].health), (2, 3))
                self.portable(g)

    def test_native_second_player_reads_own_deck_and_leaves_other_deck_untouched(self):
        for count in (24, 25):
            g = self.game(26, other_count=count, other_hand=(NATIVE,), active=2)
            self.play(g, NATIVE)
            self.assertEqual(len(g.state.players[2].deck), count - (count >= 25))
            self.assertEqual(len(g.state.players[1].deck), 26)
            self.assertEqual(g.state.players[2].mana, 8)
            self.portable(g)

    def test_constructed_thirty_slots_keep_original_size_separate_from_current_draw(self):
        r = registry()
        own = (NATIVE, 'count.fixture.prepare') + tuple(f'count.fill.{i}' for i in range(1, 29))
        other = tuple(f'count.fill.{i}' for i in range(1, 31))
        g = Game.from_decks(MatchSetup((DeckSpec('mage.hero', 'mage.power', CardClass.MAGE, own),
            DeckSpec('warrior.hero', 'warrior.power', CardClass.WARRIOR, other)), policy(r), 'coin', 85, 1), r)
        while g.state.pending_choice:
            self.choose(g)
        self.assertEqual(len(g.state.players[1].original_deck), 30)
        self.assertEqual(len(g.state.players[1].deck), 26)
        self.play(g, NATIVE)
        self.assertEqual(len(g.state.players[1].deck), 25)
        self.assertEqual(len(g.state.players[1].original_deck), 30)
        self.assertEqual(g.state.players[1].mana, 8)
        self.portable(g)

    def test_current_protocol_identity_and_previous_handler_and_schema_reject(self):
        g = self.game(25)
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version),
            (266, 'prototype-v302', CORE_EFFECTS_VERSION))
        saved = g.snapshot()
        saved['mechanics_version']['version'] = 'core-effects-v238'
        self.reject(saved)
        saved = g.snapshot()
        saved['schema_version'] = 215
        self.reject(saved)


if __name__ == '__main__':
    unittest.main()
