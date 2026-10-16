"""Original MINION printed-cost sum: one basic query, no partial real adapter."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CheckDeckCondition,
    ChoicePurpose, CostSpec, DeckCondition, DeckCostCondition, DeckCostCeilingCondition,
    DeckMinionCostCondition, DeckMinionCostSumCondition, DeckSpellSchoolCondition,
    DeckSpec, EndTurn, Game, MatchSetup, OpeningHook, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool,
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
SUPPORT = ROOT / 'data/support/starting-deck-minion-cost-sum-basics.json'
PIN = '9fcc48a7da967a9ab6d99b8f574fc70841d651101b49c8384b06a7d81b159c95'
TOTAL = DeckMinionCostSumCondition(100, 'printed')


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or [r['id'] for r in packet['records']] != ['CATA_213']:
        raise ValueError('Original MINION cost sum evidence changed')
    row = packet['records'][0]
    if canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Complete original card row changed')
    return row['data']


def pause(player):
    return RequestChoice(player, (ChoiceOption('ok', 'Continue', ()),))


def branch(player):
    return CheckDeckCondition(player, TOTAL, (GainArmor(player, 3),), (GainArmor(player, 1),))


def registry():
    evidence()
    r = opening_registry()
    for i in range(1, 31):
        for mode, kind in (('zero', CardType.MINION), ('spell', CardType.SPELL)):
            fields = {'health': 2} if kind == CardType.MINION else {}
            r.register_card(CardDefinition(f'sum.{mode}.{i}', 'Experimental original deck operand',
                kind, metadata=metadata(), **fields))
    for cost in (1, 28, 50, 99, 100, 101, 128):
        r.register_card(CardDefinition(f'sum.minion.{cost}', 'Explicit printed MINION cost',
            CardType.MINION, cost=cost, health=2, metadata=metadata()))
    r.register_card(CardDefinition('sum.no.meta', 'Diagnostic known definition without identity metadata',
        CardType.MINION, cost=100, health=2))
    r.register_behavior('sum.nop', lambda c: ())
    for cid, kind, fields in (
        ('sum.large.spell', CardType.SPELL, {}),
        ('sum.large.weapon', CardType.WEAPON, {'attack': 1, 'durability': 1}),
        ('sum.large.location', CardType.LOCATION, {'durability': 1, 'on_use': 'sum.nop'}),
        ('sum.large.hero', CardType.HERO, {'health': 30, 'hero_card': True,
            'initial_hero_power': 'mage.power', 'on_play': 'sum.nop'}),
    ):
        r.register_card(CardDefinition(cid, cid, kind, cost=100,
            metadata=metadata(CardClass.MAGE if kind == CardType.HERO else CardClass.NEUTRAL), **fields))

    def prepare(c):
        return (ChangeManaCrystals(c.player_id, 9), *(AddToHand(c.player_id, cid)
            for cid in c.state.players[c.player_id].original_deck if cid.startswith('sum.tool.')))
    r.register_behavior('sum.prepare', prepare)
    r.register_card(CardDefinition('sum.fixture.prepare', 'Explicit experimental hand preparation',
        CardType.MINION, health=1, metadata=metadata(),
        opening_hooks=(OpeningHook('after_mulligan', 'sum.prepare'),)))

    def original(c):
        return c.state.opening.original_entities[c.player_id - 1][
            c.state.players[c.player_id].original_deck.index('sum.minion.100')]

    def fail(c):
        raise ResolutionError('Expected late sum branch failure')
    r.register_behavior('sum.fail', fail)
    scripts = {
        'sum.tool.local': lambda c: (ModifyCost(original(c), CostSpec(set_to=0), c.source_id),),
        'sum.tool.external': lambda c: (AddCostModifier(c.player_id, CostSpec(set_to=0), c.source_id),),
        'sum.tool.add': lambda c: (AddToDeck(c.player_id, 'sum.minion.100'),),
        'sum.tool.clear': lambda c: (DestroyDeckMatching(c.player_id, count=40, reveal=False),),
        'sum.tool.draw': lambda c: (Draw(c.player_id),),
        'sum.tool.face': lambda c: (TransformCapturedMinion(
            CardReference.capture(c.state.entities[original(c)]), 'sum.minion.1'),),
        'sum.tool.check': lambda c: (branch(c.player_id),),
        'sum.tool.wait': lambda c: (pause(c.player_id), branch(c.player_id)),
        'sum.tool.selected': lambda c: (CheckDeckCondition(c.player_id, TOTAL,
            (pause(c.player_id), AddToDeck(c.player_id, 'sum.minion.100'), GainArmor(c.player_id, 3)),
            (pause(c.player_id), DestroyDeckMatching(c.player_id, count=40, reveal=False), GainArmor(c.player_id, 1))),),
        'sum.tool.fail': lambda c: (branch(c.player_id), InvokeBehavior('sum.fail', c.source_id, c.player_id)),
        'sum.tool.wait.fail': lambda c: (pause(c.player_id), branch(c.player_id),
            InvokeBehavior('sum.fail', c.source_id, c.player_id)),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))
    for cid, fn in (
        ('sum.fixture.start', lambda c: (branch(c.player_id),)),
        ('sum.fixture.wait.before', lambda c: (pause(c.player_id), branch(c.player_id))),
        ('sum.fixture.wait.selected', lambda c: (CheckDeckCondition(c.player_id, TOTAL,
            (pause(c.player_id), GainArmor(c.player_id, 3)), (pause(c.player_id), GainArmor(c.player_id, 1))),)),
    ):
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, 'Explicit synthetic opening gate', CardType.MINION,
            health=1, metadata=metadata(), opening_hooks=(OpeningHook('before_deal', cid),)))
    return r


class StartingDeckMinionCostSumTests(unittest.TestCase):
    def match(self, extra=(), *, mode='zero', other_extra=(), other_mode='zero', first=1, finish=True):
        r = registry()
        def cards(mode, prefix):
            if any(cid.startswith('sum.tool.') for cid in prefix):
                prefix = ('sum.fixture.prepare',) + tuple(prefix)
            return tuple(prefix) + tuple(f'sum.{mode}.{i}' for i in range(1, 31 - len(prefix)))
        own, other = cards(mode, extra), cards(other_mode, other_extra)
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

    def query(self, g, total=100, player=1):
        return matches_deck_condition(g.state, g.registry, player, DeckMinionCostSumCondition(total, 'printed'))

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

    def test_complete_raw_pin_demands_starting_minions_and_no_partial_native_adapter(self):
        packet, raw, r = json.loads(SUPPORT.read_bytes()), evidence(), registry()
        self.assertEqual(hashlib.sha256((ROOT / 'data/extracted/cards.json').read_bytes()).hexdigest(), packet['source_sha256'])
        self.assertEqual((raw['id'], raw['cost'], raw['attack'], raw['health']), ('CATA_213', 6, 6, 6))
        self.assertIn('starting minions', raw['text_en'])
        self.assertIn('100, split 100 stats', raw['text_en'])
        with self.assertRaises(UnsupportedDefinitionError):
            r.card('CATA_213')

    def test_exact_equality_distinguishes_99_100_and_101(self):
        for value in (99, 100, 101):
            with self.subTest(value=value):
                g = self.match((f'sum.minion.{value}',))
                self.assertEqual(self.query(g), value == 100)

    def test_totals_are_parameterized_and_not_capped_at_a_card_cost(self):
        for value in (1, 50, 128):
            with self.subTest(value=value):
                g = self.match((f'sum.minion.{value}',))
                self.assertTrue(self.query(g, value))
                self.assertFalse(self.query(g, value - 1))
        self.assertTrue(self.query(self.match(('sum.minion.100', 'sum.minion.28')), 128))

    def test_duplicate_original_minion_entries_each_contribute(self):
        g = self.match(('sum.minion.50', 'sum.minion.50'))
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, 50))
        self.assertEqual(g.state.players[1].original_deck.count('sum.minion.50'), 2)
        self.portable(g)

    def test_non_minion_card_types_are_excluded_even_when_their_cost_is_100(self):
        extra = ('sum.large.spell', 'sum.large.weapon', 'sum.large.location', 'sum.large.hero')
        self.assertTrue(self.query(self.match(extra), 0))
        self.assertFalse(self.query(self.match(extra)))
        self.assertTrue(self.query(self.match(extra + ('sum.minion.100',))))

    def test_zero_sum_is_valid_with_zero_cost_minions_or_no_minions(self):
        for mode in ('zero', 'spell'):
            g = self.match(mode=mode)
            self.assertTrue(self.query(g, 0))
            self.assertFalse(self.query(g, 1))
            self.assertEqual(len(g.state.players[1].original_deck), 30)

    def test_scenario_current_deck_and_forged_tuple_do_not_establish_origin(self):
        r = registry()
        current = ('sum.minion.100',) + tuple(f'sum.zero.{i}' for i in range(1, 30))
        g = Game.from_scenario(Scenario((PlayerSetup('mage.hero', deck=current),
            PlayerSetup('warrior.hero')), seed=85), r)
        with self.assertRaises(UnknownDeckFacts):
            self.query(g, 0)
        g.state.players[1].original_deck = ('sum.minion.100',)
        with self.assertRaises(UnknownDeckFacts):
            self.query(g)

    def test_both_players_read_their_own_original_total_when_second_player_starts(self):
        g = self.match(('sum.minion.100',), other_extra=('sum.minion.99',), first=2)
        self.assertTrue(self.query(g, player=1))
        self.assertFalse(self.query(g, player=2))
        self.assertTrue(self.query(g, 99, player=2))

    def test_host_operand_diagnostics_need_no_unrelated_metadata_but_reject_unknown_rows(self):
        # Detached host operands test query requirements, not valid native matches.
        g = self.match()
        state = deepcopy(g.state)
        state.players[1].original_deck = ('sum.no.meta',)
        self.assertTrue(matches_deck_condition(state, g.registry, 1, TOTAL))
        for known in ('sum.minion.100', 'sum.minion.99', 'sum.large.spell'):
            state.players[1].original_deck = (known, 'unknown.sum.definition')
            with self.assertRaises(UnsupportedDefinitionError):
                matches_deck_condition(state, g.registry, 1, TOTAL)

    def test_query_does_not_change_rng_history_events_actions_or_origin(self):
        g = self.match(('sum.minion.100',))
        before, actions = g.snapshot(), g.legal_actions()
        for total in (99, 100, 101):
            self.query(g, total)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.legal_actions(), actions)

    def test_full_mulligan_and_coin_preserve_original_sum(self):
        g = self.match(('sum.minion.100',), finish=False)
        while g.state.pending_choice:
            self.choose(g, tuple(o.id for o in g.state.pending_choice.options))
        self.assertTrue(self.query(g))
        self.assertEqual(tuple(map(len, g.state.opening.original_entities)), (30, 30))
        self.assertIn('coin', [g.state.entities[i].card_id for i in g.state.players[2].hand])
        self.portable(g)

    def test_local_fee_change_does_not_rewrite_original_printed_sum(self):
        g = self.match(('sum.minion.100', 'sum.tool.local'))
        identity = g.state.opening.original_entities[0][g.state.players[1].original_deck.index('sum.minion.100')]
        self.play(g, 'sum.tool.local')
        self.assertEqual(local_cost(g.state.entities[identity])[0], 0)
        self.assertTrue(self.query(g))
        self.portable(g)

    def test_external_fee_quote_does_not_substitute_original_printed_basis(self):
        g = self.match(('sum.minion.100', 'sum.tool.external'))
        self.play(g, 'sum.tool.external')
        identity = g.state.opening.original_entities[0][g.state.players[1].original_deck.index('sum.minion.100')]
        entity = g.state.entities[identity]
        self.assertEqual(quote_cost(g.state, g.registry, entity).amount, 0)
        self.assertTrue(self.query(g))

    def test_current_add_draw_and_deck_removal_leave_original_sum_intact(self):
        g = self.match(('sum.minion.100', 'sum.tool.add', 'sum.tool.draw', 'sum.tool.clear'))
        original = g.state.players[1].original_deck
        for cid in ('sum.tool.add', 'sum.tool.draw', 'sum.tool.clear'):
            self.play(g, cid)
            self.assertTrue(self.query(g))
            self.assertEqual(g.state.players[1].original_deck, original)
        self.assertEqual(g.state.players[1].deck, [])
        self.portable(g)

    def test_original_physical_minion_face_change_does_not_rewrite_origin(self):
        g = self.match(('sum.minion.100', 'sum.tool.face'))
        identity = g.state.opening.original_entities[0][g.state.players[1].original_deck.index('sum.minion.100')]
        self.play(g, 'sum.tool.face')
        self.assertEqual(g.state.entities[identity].card_id, 'sum.minion.1')
        self.assertTrue(self.query(g))
        self.portable(g)

    def test_natural_turns_do_not_replace_starting_total_with_remaining_deck(self):
        g = self.match(('sum.minion.100',))
        for _ in range(4):
            g.apply(EndTurn(g.state.active_player))
            self.assertTrue(self.query(g))
        self.portable(g)

    def test_before_deal_branch_reads_each_original_deck(self):
        g = self.match(('sum.fixture.start', 'sum.minion.100'),
            other_extra=('sum.fixture.start', 'sum.minion.99'), finish=False)
        self.assertEqual((self.armor(g), self.armor(g, 2)), (3, 1))
        self.finish(g)
        self.portable(g)

    def test_player_command_pays_and_executes_one_selected_branch(self):
        g = self.match(('sum.minion.100', 'sum.tool.check'))
        port = g.for_player(1)
        dto = port.legal_actions()
        ref = next(row['ref'] for row in g.observe(1)['players'][0]['hand'] if row['card_id'] == 'sum.tool.check')
        action = next(row for row in dto['actions'] if row.get('card') == ref)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((self.armor(g), g.state.players[1].mana), (3, 10))
        self.assertEqual(len(g.state.play_history), 1)

    def test_opening_unexecuted_and_selected_branches_resume_portably(self):
        for fixture in ('sum.fixture.wait.before', 'sum.fixture.wait.selected'):
            for cost, armor in ((100, 3), (99, 1)):
                g = self.match((fixture, f'sum.minion.{cost}'), finish=False)
                restored = self.portable(g)
                self.finish(g)
                self.finish(restored)
                self.assertEqual(g.snapshot(), restored.snapshot())
                self.assertEqual(self.armor(g), armor)

    def test_unexecuted_play_branch_restores_for_both_original_results(self):
        for cost, armor in ((100, 3), (99, 1)):
            g = self.match((f'sum.minion.{cost}', 'sum.tool.wait'))
            self.play(g, 'sum.tool.wait')
            restored = self.portable(g)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(self.armor(g), armor)

    def test_selected_branch_survives_wait_and_current_deck_changes(self):
        for cost, armor in ((100, 3), (99, 1)):
            g = self.match((f'sum.minion.{cost}', 'sum.tool.selected'))
            self.play(g, 'sum.tool.selected')
            restored = self.portable(g)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(self.armor(g), armor)
            self.assertEqual(self.query(g), cost == 100)

    def test_late_action_and_choice_failures_roll_back_branch_effects(self):
        for cid in ('sum.tool.fail', 'sum.tool.wait.fail'):
            g = self.match(('sum.minion.100', cid))
            if cid.endswith('wait.fail'):
                self.play(g, cid)
            before = g.snapshot()
            with self.assertRaises(ResolutionError):
                self.choose(g) if cid.endswith('wait.fail') else self.play(g, cid)
            self.assertEqual(g.snapshot(), before)

    def test_new_payload_and_old_five_conditions_roundtrip_without_field_changes(self):
        g = self.match()
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        declarations = ((TOTAL, {'total_cost', 'cost_basis', 'scope'}),
            (DeckCondition(), {'scope', 'predicate'}),
            (DeckCostCondition(4, 'local'), {'cost', 'cost_basis', 'scope'}),
            (DeckSpellSchoolCondition(SpellSchool.SHADOW), {'spell_school', 'scope'}),
            (DeckMinionCostCondition(4, 'less', 'local'), {'cost', 'comparison', 'cost_basis', 'scope'}),
            (DeckCostCeilingCondition(3, 'printed'), {'cost_limit', 'cost_basis', 'scope'}))
        for declaration, fields in declarations:
            wire = codec.encode(declaration)
            self.assertEqual(codec.decode(wire), declaration)
            self.assertEqual(set(wire['fields']), fields)
        wire = codec.encode(branch(1))
        self.assertEqual(set(wire['fields']), {'player_id', 'condition', 'on_match', 'on_miss'})
        self.assertEqual(codec.decode(wire), branch(1))

    def test_declaration_requires_exact_nonnegative_integer_printed_and_starting(self):
        cases = [(value, 'printed', 'starting') for value in (True, -1, 100.0, '100', None)]
        cases += [(100, value, 'starting') for value in (True, None, 'local', 'external', '')]
        cases += [(100, 'printed', value) for value in (True, None, 'current', 'hand', '')]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                DeckMinionCostSumCondition(*args)
        with self.assertRaises(TypeError):
            DeckMinionCostSumCondition(100)

    def test_waiting_snapshot_rejects_invalid_sum_payloads_and_extra_fields(self):
        g = self.match(('sum.minion.100', 'sum.tool.wait'))
        self.play(g, 'sum.tool.wait')
        for field, value in (('total_cost', True), ('total_cost', -1), ('total_cost', 100.0),
                ('cost_basis', 'local'), ('scope', 'current'), ('invented', 1)):
            saved = g.snapshot()
            self.nested(saved['resolution_frame'], 'DeckMinionCostSumCondition')['fields'][field] = value
            self.reject(saved)

    def test_rehashed_original_deck_tampering_is_rejected(self):
        g = self.match(('sum.minion.100',))
        saved = g.snapshot()
        saved['state']['players']['1']['original_deck'][0] = 'sum.minion.99'
        self.reject(saved)

    def test_player_projections_do_not_expose_original_total_or_private_conditions(self):
        g = self.match(('sum.fixture.wait.before', 'sum.minion.100'), finish=False)
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player)) + json.dumps(g.for_player(player).legal_actions())
            for private in ('DeckMinionCostSumCondition', 'total_cost', 'cost_basis',
                    'original_deck', 'resolution_frame', 'sum.minion.100'):
                self.assertNotIn(private, text)

    def test_current_versions_reject_old_engine_and_old_schema(self):
        g = self.match()
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version),
            (SNAPSHOT_SCHEMA_VERSION, 'prototype-v302', CORE_EFFECTS_VERSION))
        for key, value in (('schema_version', 215), ('mechanics_version', {'version': 'core-effects-v235'})):
            saved = g.snapshot()
            if key == 'mechanics_version':
                saved[key]['version'] = value['version']
            else:
                saved[key] = value
            self.reject(saved)
