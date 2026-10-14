"""Distinct original printed costs: explicit minimum, no custom-location body."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CheckDeckCondition,
    ChoicePurpose, CostSpec, DeckCondition, DeckCostCondition, DeckCostCeilingCondition,
    DeckCostDiversityCondition, DeckMinionCostCondition, DeckMinionCostSumCondition,
    DeckSpellSchoolCondition, DeckSpec, EndTurn, Game, MatchSetup, OpeningHook, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool,
    UnknownDeckFacts, matches_deck_condition)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost, quote_cost
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeManaCrystals,
    ChoiceOption, Draw, GainArmor, InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from test_current_deck_empty_basics import rehash
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT/'data/support/starting-deck-cost-diversity-basics.json'
PIN = 'c82669854668f00c5d526cb2ad30dc481649abc409e5a94877ba7a151361f08a'
DIVERSITY = DeckCostDiversityCondition(10, 'printed')


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or [r['id'] for r in packet['records']] != ['TLC_100']:
        raise ValueError('Complete starting cost diversity evidence changed')
    row = packet['records'][0]
    if canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Complete original card row changed')
    return row['data']


def cost_faces(count):
    # The real 30-slot fixture fills remaining slots with zero-cost faces.
    return tuple(f'diverse.minion.{value}' for value in range(1, count))


def pause(player):
    return RequestChoice(player, (ChoiceOption('ok', 'Continue', ()),))


def branch(player):
    return CheckDeckCondition(player, DIVERSITY, (GainArmor(player, 3),), (GainArmor(player, 1),))


def registry():
    evidence()
    r = opening_registry()
    for i in range(1, 31):
        r.register_card(CardDefinition(f'diverse.zero.{i}', 'Experimental zero-cost original slot',
            CardType.MINION, health=2, metadata=metadata()))
    for value in (*range(1, 13), 101):
        r.register_card(CardDefinition(f'diverse.minion.{value}', 'Explicit printed cost operand',
            CardType.MINION, cost=value, health=2, metadata=metadata()))
    r.register_card(CardDefinition('diverse.other.one', 'Different identity with the same printed cost',
        CardType.MINION, cost=1, health=2, metadata=metadata()))
    r.register_card(CardDefinition('diverse.no.meta', 'Diagnostic known definition without identity metadata',
        CardType.MINION, cost=9, health=2))
    r.register_behavior('diverse.nop', lambda c: ())
    for cid, kind, cost, fields in (
        ('diverse.spell.6', CardType.SPELL, 6, {}),
        ('diverse.weapon.7', CardType.WEAPON, 7, {'attack': 1, 'durability': 1}),
        ('diverse.location.8', CardType.LOCATION, 8, {'durability': 1, 'on_use': 'diverse.nop'}),
        ('diverse.hero.9', CardType.HERO, 9, {'health': 30, 'hero_card': True,
            'initial_hero_power': 'mage.power', 'on_play': 'diverse.nop'}),
    ):
        r.register_card(CardDefinition(cid, cid, kind, cost=cost,
            metadata=metadata(CardClass.MAGE if kind == CardType.HERO else CardClass.NEUTRAL), **fields))

    def prepare(c):
        return (ChangeManaCrystals(c.player_id, 9), *(AddToHand(c.player_id, cid)
            for cid in c.state.players[c.player_id].original_deck if cid.startswith('diverse.tool.')))
    r.register_behavior('diverse.prepare', prepare)
    r.register_card(CardDefinition('diverse.fixture.prepare', 'Explicit experimental hand preparation',
        CardType.MINION, health=1, metadata=metadata(),
        opening_hooks=(OpeningHook('after_mulligan', 'diverse.prepare'),)))

    def original(c):
        return c.state.opening.original_entities[c.player_id-1][
            c.state.players[c.player_id].original_deck.index('diverse.minion.9')]

    def fail(c):
        raise ResolutionError('Expected late diversity branch failure')
    r.register_behavior('diverse.fail', fail)
    scripts = {
        'diverse.tool.local': lambda c: (ModifyCost(original(c), CostSpec(set_to=0), c.source_id),),
        'diverse.tool.external': lambda c: (AddCostModifier(c.player_id, CostSpec(set_to=0), c.source_id),),
        'diverse.tool.add': lambda c: (AddToDeck(c.player_id, 'diverse.minion.12'),),
        'diverse.tool.draw': lambda c: (Draw(c.player_id),),
        'diverse.tool.clear': lambda c: (DestroyDeckMatching(c.player_id, count=40, reveal=False),),
        'diverse.tool.face': lambda c: (TransformCapturedMinion(
            CardReference.capture(c.state.entities[original(c)]), 'diverse.minion.1'),),
        'diverse.tool.check': lambda c: (branch(c.player_id),),
        'diverse.tool.wait': lambda c: (pause(c.player_id), branch(c.player_id)),
        'diverse.tool.selected': lambda c: (CheckDeckCondition(c.player_id, DIVERSITY,
            (pause(c.player_id), AddToDeck(c.player_id, 'diverse.minion.12'), GainArmor(c.player_id, 3)),
            (pause(c.player_id), DestroyDeckMatching(c.player_id, count=40, reveal=False), GainArmor(c.player_id, 1))),),
        'diverse.tool.fail': lambda c: (branch(c.player_id), InvokeBehavior('diverse.fail', c.source_id, c.player_id)),
        'diverse.tool.wait.fail': lambda c: (pause(c.player_id), branch(c.player_id),
            InvokeBehavior('diverse.fail', c.source_id, c.player_id)),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))
    for cid, fn in (
        ('diverse.fixture.start', lambda c: (branch(c.player_id),)),
        ('diverse.fixture.wait.before', lambda c: (pause(c.player_id), branch(c.player_id))),
        ('diverse.fixture.wait.selected', lambda c: (CheckDeckCondition(c.player_id, DIVERSITY,
            (pause(c.player_id), GainArmor(c.player_id, 3)), (pause(c.player_id), GainArmor(c.player_id, 1))),)),
    ):
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, 'Explicit synthetic opening gate', CardType.MINION,
            health=1, metadata=metadata(), opening_hooks=(OpeningHook('before_deal', cid),)))
    return r


class StartingDeckCostDiversityTests(unittest.TestCase):
    def match(self, extra=(), *, other_extra=(), first=1, finish=True):
        r = registry()
        def cards(prefix):
            if any(cid.startswith('diverse.tool.') for cid in prefix):
                prefix = ('diverse.fixture.prepare',) + tuple(prefix)
            return tuple(prefix) + tuple(f'diverse.zero.{i}' for i in range(1, 31-len(prefix)))
        own, other = cards(extra), cards(other_extra)
        g = Game.from_decks(MatchSetup((DeckSpec('mage.hero', 'mage.power', CardClass.MAGE, own),
            DeckSpec('warrior.hero', 'warrior.power', CardClass.WARRIOR, other)), policy(r), 'coin', 85, first), r)
        return self.finish(g) if finish else g

    def finish(self, g):
        while g.state.pending_choice:
            self.choose(g)
        return g

    def choose(self, g, options=None):
        q = g.state.pending_choice
        if options is None:
            options = () if q.purpose == ChoicePurpose.MULLIGAN else ('ok',)
        g.apply(SelectChoice(q.player_id, q.id, tuple(options)))

    def query(self, g, minimum=10, player=1):
        return matches_deck_condition(g.state, g.registry, player, DeckCostDiversityCondition(minimum, 'printed'))

    def play(self, g, cid):
        player = g.state.active_player
        identity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, identity))
        return identity

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
            if value.get('type', '').endswith('.'+name):
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

    def test_complete_raw_requires_starting_different_costs_without_partial_native_adapter(self):
        packet, raw, r = json.loads(SUPPORT.read_bytes()), evidence(), registry()
        self.assertEqual(hashlib.sha256((ROOT/'data/extracted/cards.json').read_bytes()).hexdigest(), packet['source_sha256'])
        self.assertEqual((raw['id'], raw['cost'], raw['attack'], raw['health']), ('TLC_100', 4, 3, 5))
        self.assertIn('started with 10 cards of different Costs', raw['text_en'])
        self.assertEqual(raw['tags']['SHOULD_TRACK_DECK_COST_COUNT'], 1)
        with self.assertRaises(UnsupportedDefinitionError):
            r.card('TLC_100')

    def test_minimum_threshold_distinguishes_9_10_and_11_values(self):
        for count in (9, 10, 11):
            with self.subTest(count=count):
                self.assertEqual(self.query(self.match(cost_faces(count))), count >= 10)

    def test_minimum_is_parameterized_and_zero_is_a_valid_threshold(self):
        g = self.match(cost_faces(12))
        for minimum in (0, 1, 10, 12, 13, 30):
            self.assertEqual(self.query(g, minimum), minimum <= 12)

    def test_duplicate_faces_and_different_ids_with_same_cost_count_once(self):
        g = self.match(('diverse.minion.1', 'diverse.minion.1', 'diverse.other.one'))
        self.assertTrue(self.query(g, 2))
        self.assertFalse(self.query(g, 3))
        self.assertFalse(self.query(g))
        self.assertEqual(g.state.players[1].original_deck.count('diverse.minion.1'), 2)
        self.portable(g)

    def test_all_five_constructed_card_kinds_supply_original_cost_values(self):
        extra = cost_faces(6) + ('diverse.spell.6', 'diverse.weapon.7', 'diverse.location.8', 'diverse.hero.9')
        g = self.match(extra)
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, 11))

    def test_thirty_same_cost_cards_are_one_value_including_zero(self):
        g = self.match()
        self.assertEqual(len(g.state.players[1].original_deck), 30)
        self.assertTrue(self.query(g, 1))
        self.assertFalse(self.query(g, 2))
        self.assertFalse(self.query(g))

    def test_cost_values_can_have_gaps_and_exceed_the_mana_cap(self):
        g = self.match(('diverse.minion.1', 'diverse.minion.101'))
        self.assertTrue(self.query(g, 3))
        self.assertFalse(self.query(g, 4))
        self.assertTrue(self.query(self.match(cost_faces(10) + ('diverse.minion.101',)), 11))

    def test_current_scenario_and_forged_tuple_do_not_establish_starting_facts(self):
        r = registry()
        current = cost_faces(10) + tuple(f'diverse.zero.{i}' for i in range(1, 22))
        g = Game.from_scenario(Scenario((PlayerSetup('mage.hero', deck=current), PlayerSetup('warrior.hero'))), r)
        self.assertEqual(len(g.state.players[1].deck), 30)
        for forge in (False, True):
            if forge:
                g.state.players[1].original_deck = current
            with self.assertRaises(UnknownDeckFacts):
                self.query(g)
            with self.assertRaises(UnknownDeckFacts):
                self.query(g, 0)

    def test_each_player_reads_own_original_values_when_second_player_starts(self):
        g = self.match(cost_faces(10), other_extra=cost_faces(9), first=2)
        self.assertTrue(self.query(g, player=1))
        self.assertFalse(self.query(g, player=2))
        self.assertTrue(self.query(g, 9, player=2))

    def test_host_diagnostics_need_no_identity_metadata_and_reject_late_unknown_definition(self):
        # Detached diagnostic operands are not advertised as valid native games.
        g = self.match()
        state = deepcopy(g.state)
        state.players[1].original_deck = ('diverse.no.meta',)
        self.assertTrue(matches_deck_condition(state, g.registry, 1, DeckCostDiversityCondition(1, 'printed')))
        state.players[1].original_deck = cost_faces(11) + ('unknown.diverse.definition',)
        with self.assertRaises(UnsupportedDefinitionError):
            matches_deck_condition(state, g.registry, 1, DIVERSITY)

    def test_pure_query_preserves_rng_events_history_actions_and_origins(self):
        g = self.match(cost_faces(10))
        before, actions = g.snapshot(), g.legal_actions()
        for minimum in (9, 10, 11):
            self.query(g, minimum)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.legal_actions(), actions)

    def test_full_mulligan_and_coin_keep_original_distinct_values(self):
        g = self.match(cost_faces(10), finish=False)
        while g.state.pending_choice:
            self.choose(g, tuple(o.id for o in g.state.pending_choice.options))
        self.assertTrue(self.query(g))
        self.assertIn('coin', [g.state.entities[i].card_id for i in g.state.players[2].hand])
        self.portable(g)

    def test_local_fee_change_does_not_remove_an_original_distinct_value(self):
        g = self.match(cost_faces(10) + ('diverse.tool.local',))
        identity = g.state.opening.original_entities[0][g.state.players[1].original_deck.index('diverse.minion.9')]
        self.play(g, 'diverse.tool.local')
        self.assertEqual(local_cost(g.state.entities[identity])[0], 0)
        self.assertTrue(self.query(g))
        self.portable(g)

    def test_external_fee_quote_does_not_replace_original_printed_costs(self):
        g = self.match(cost_faces(10) + ('diverse.tool.external',))
        identity = g.state.opening.original_entities[0][g.state.players[1].original_deck.index('diverse.minion.9')]
        self.play(g, 'diverse.tool.external')
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[identity]).amount, 0)
        self.assertTrue(self.query(g))

    def test_generated_value_draw_and_current_deck_clear_leave_starting_diversity_fixed(self):
        g = self.match(cost_faces(10) + ('diverse.tool.add', 'diverse.tool.draw', 'diverse.tool.clear'))
        original = g.state.players[1].original_deck
        self.play(g, 'diverse.tool.add')
        self.assertIn('diverse.minion.12', [g.state.entities[i].card_id for i in g.state.players[1].deck])
        for cid in ('diverse.tool.draw', 'diverse.tool.clear'):
            self.play(g, cid)
            self.assertTrue(self.query(g))
            self.assertFalse(self.query(g, 11))
            self.assertEqual(g.state.players[1].original_deck, original)
        self.assertEqual(g.state.players[1].deck, [])
        self.portable(g)

    def test_original_physical_face_change_preserves_original_value(self):
        g = self.match(cost_faces(10) + ('diverse.tool.face',))
        identity = g.state.opening.original_entities[0][g.state.players[1].original_deck.index('diverse.minion.9')]
        self.play(g, 'diverse.tool.face')
        self.assertEqual(g.state.entities[identity].card_id, 'diverse.minion.1')
        self.assertTrue(self.query(g))
        self.portable(g)

    def test_natural_turns_do_not_replace_original_values_with_remaining_deck(self):
        g = self.match(cost_faces(10))
        for _ in range(4):
            g.apply(EndTurn(g.state.active_player))
            self.assertTrue(self.query(g))
        self.portable(g)

    def test_before_deal_gate_uses_original_values_for_each_player(self):
        g = self.match(cost_faces(10) + ('diverse.fixture.start',),
            other_extra=cost_faces(9) + ('diverse.fixture.start',), finish=False)
        self.assertEqual((self.armor(g), self.armor(g, 2)), (3, 1))
        self.finish(g)
        self.portable(g)

    def test_player_command_executes_the_branch_once(self):
        g = self.match(cost_faces(10) + ('diverse.tool.check',))
        port = g.for_player(1)
        dto = port.legal_actions()
        ref = next(row['ref'] for row in g.observe(1)['players'][0]['hand'] if row['card_id'] == 'diverse.tool.check')
        action = next(row for row in dto['actions'] if row.get('card') == ref)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((self.armor(g), g.state.players[1].mana, len(g.state.play_history)), (3, 10, 1))

    def test_opening_unexecuted_and_selected_gates_resume_on_independent_registry(self):
        for fixture in ('diverse.fixture.wait.before', 'diverse.fixture.wait.selected'):
            for count, armor in ((10, 3), (9, 1)):
                g = self.match(cost_faces(count) + (fixture,), finish=False)
                restored = self.portable(g)
                self.finish(g)
                self.finish(restored)
                self.assertEqual(g.snapshot(), restored.snapshot())
                self.assertEqual(self.armor(g), armor)

    def test_unexecuted_play_gate_resumes_for_both_original_results(self):
        for count, armor in ((10, 3), (9, 1)):
            g = self.match(cost_faces(count) + ('diverse.tool.wait',))
            self.play(g, 'diverse.tool.wait')
            restored = self.portable(g)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(self.armor(g), armor)

    def test_selected_branch_keeps_its_sequence_through_wait_and_current_deck_changes(self):
        for count, armor in ((10, 3), (9, 1)):
            g = self.match(cost_faces(count) + ('diverse.tool.selected',))
            self.play(g, 'diverse.tool.selected')
            restored = self.portable(g)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(self.armor(g), armor)
            self.assertEqual(self.query(g), count >= 10)

    def test_late_action_and_choice_failures_roll_back_all_effects(self):
        for cid in ('diverse.tool.fail', 'diverse.tool.wait.fail'):
            g = self.match(cost_faces(10) + (cid,))
            if cid.endswith('wait.fail'):
                self.play(g, cid)
            before = g.snapshot()
            with self.assertRaises(ResolutionError):
                self.choose(g) if cid.endswith('wait.fail') else self.play(g, cid)
            self.assertEqual(g.snapshot(), before)

    def test_payload_and_all_six_old_declarations_roundtrip_with_old_fields(self):
        g = self.match()
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        declarations = ((DIVERSITY, {'min_distinct_costs', 'cost_basis', 'scope'}),
            (DeckCondition(), {'scope', 'predicate'}),
            (DeckCostCondition(4, 'local'), {'cost', 'cost_basis', 'scope'}),
            (DeckSpellSchoolCondition(SpellSchool.SHADOW), {'spell_school', 'scope'}),
            (DeckMinionCostCondition(4, 'less', 'local'), {'cost', 'comparison', 'cost_basis', 'scope'}),
            (DeckCostCeilingCondition(3, 'printed'), {'cost_limit', 'cost_basis', 'scope'}),
            (DeckMinionCostSumCondition(100, 'printed'), {'total_cost', 'cost_basis', 'scope'}))
        for declaration, fields in declarations:
            wire = codec.encode(declaration)
            self.assertEqual(codec.decode(wire), declaration)
            self.assertEqual(set(wire['fields']), fields)
        wire = codec.encode(branch(1))
        self.assertEqual(set(wire['fields']), {'player_id', 'condition', 'on_match', 'on_miss'})
        self.assertEqual(codec.decode(wire), branch(1))

    def test_declaration_requires_strict_nonnegative_minimum_printed_and_starting(self):
        cases = [(value, 'printed', 'starting') for value in (True, -1, 10.0, '10', None)]
        cases += [(10, value, 'starting') for value in (True, None, 'local', 'external', '')]
        cases += [(10, 'printed', value) for value in (True, None, 'current', 'hand', '')]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                DeckCostDiversityCondition(*args)
        with self.assertRaises(TypeError):
            DeckCostDiversityCondition(10)

    def test_waiting_snapshot_rejects_invalid_diversity_payloads_and_extra_fields(self):
        g = self.match(cost_faces(10) + ('diverse.tool.wait',))
        self.play(g, 'diverse.tool.wait')
        for field, value in (('min_distinct_costs', True), ('min_distinct_costs', -1), ('min_distinct_costs', 10.0),
                ('cost_basis', 'local'), ('scope', 'current'), ('invented', 1)):
            saved = g.snapshot()
            self.nested(saved['resolution_frame'], 'DeckCostDiversityCondition')['fields'][field] = value
            self.reject(saved)

    def test_rehashed_constructed_original_deck_tampering_is_rejected(self):
        g = self.match(cost_faces(10))
        saved = g.snapshot()
        saved['state']['players']['1']['original_deck'][0] = 'diverse.minion.2'
        self.reject(saved)

    def test_player_projections_hide_original_values_and_private_conditions(self):
        g = self.match(cost_faces(10) + ('diverse.fixture.wait.before',), finish=False)
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player)) + json.dumps(g.for_player(player).legal_actions())
            for private in ('DeckCostDiversityCondition', 'min_distinct_costs', 'cost_basis',
                    'original_deck', 'resolution_frame', 'diverse.minion.9'):
                self.assertNotIn(private, text)

    def test_current_versions_and_old_same_layout_handler_and_schema_rejections(self):
        g = self.match()
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version),
            (266, 'prototype-v302', CORE_EFFECTS_VERSION))
        saved = g.snapshot()
        saved['mechanics_version']['version'] = 'core-effects-v236'
        self.reject(saved)
        saved = g.snapshot()
        saved['schema_version'] = 215
        self.reject(saved)
