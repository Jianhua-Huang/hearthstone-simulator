"""Original printed cost ceiling; explicitly synthetic gates, no partial Chef card."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CheckDeckCondition, ChoicePurpose,
    CostSpec, DeckCondition, DeckCostCondition, DeckCostCeilingCondition, DeckMinionCostCondition,
    DeckSpellSchoolCondition, DeckSpec, EndTurn, Game, MatchSetup, OpeningHook, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool,
    UnknownDeckFacts, matches_deck_condition)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost, quote_cost
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeManaCrystals, ChoiceOption,
    Draw, GainArmor, InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from test_current_deck_empty_basics import rehash
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/starting-deck-cost-ceiling-basics.json'
PIN = 'c3f3872aab0e6ca1f872155110a2522cadf740342c73f7e73e20d199e8b0c1f6'
CEILING = DeckCostCeilingCondition(3, 'printed')


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or [r['id'] for r in packet['records']] != ['JAIL_860']:
        raise ValueError('Complete original cost ceiling evidence changed')
    row = packet['records'][0]
    if canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Complete original card row changed')
    return row['data']


def pause(player):
    return RequestChoice(player, (ChoiceOption('ok', 'Continue', ()),))


def branch(player):
    return CheckDeckCondition(player, CEILING, (GainArmor(player, 3),), (GainArmor(player, 1),))


def registry():
    evidence()
    r = opening_registry()
    for i in range(1, 31):
        for prefix, cost in (('low', 2), ('zero', 0)):
            r.register_card(CardDefinition(f'ceiling.{prefix}.{i}', 'Experimental original cost operand',
                CardType.MINION, cost=cost, health=2, metadata=metadata()))
    r.register_behavior('ceiling.nop', lambda c: ())
    for cid, kind, cost, fields in (
        ('ceiling.equal', CardType.MINION, 3, dict(health=2)),
        ('ceiling.high', CardType.MINION, 4, dict(health=2)),
        ('ceiling.spell', CardType.SPELL, 3, {}),
        ('ceiling.weapon', CardType.WEAPON, 3, dict(attack=1, durability=1)),
        ('ceiling.location', CardType.LOCATION, 3, dict(durability=1, on_use='ceiling.nop')),
        ('ceiling.hero', CardType.HERO, 3, dict(health=30, hero_card=True, initial_hero_power='mage.power', on_play='ceiling.nop')),
        ('ceiling.high.spell', CardType.SPELL, 4, {}),
        ('ceiling.large', CardType.SPELL, 101, {}),
    ):
        r.register_card(CardDefinition(cid, cid, kind, cost=cost,
            metadata=metadata(CardClass.MAGE if kind == CardType.HERO else CardClass.NEUTRAL), **fields))
    r.register_card(CardDefinition('ceiling.no.meta', 'Known printed cost without unrelated class facts', CardType.MINION, cost=3, health=2))
    def prepare(c):
        return (ChangeManaCrystals(c.player_id, 9), *(AddToHand(c.player_id, cid)
            for cid in c.state.players[c.player_id].original_deck if cid.startswith('ceiling.tool.')))
    r.register_behavior('ceiling.prepare', prepare)
    r.register_card(CardDefinition('ceiling.fixture.prepare', 'Explicit experimental hand preparation', CardType.MINION,
        health=1, metadata=metadata(), opening_hooks=(OpeningHook('after_mulligan', 'ceiling.prepare'),)))
    def fail(c):
        raise ResolutionError('Expected late ceiling failure')
    r.register_behavior('ceiling.fail', fail)
    def set_first(c, amount):
        return ModifyCost(c.state.players[c.player_id].deck[0], CostSpec(set_to=amount), c.source_id)
    scripts = {
        'ceiling.tool.high': lambda c: (set_first(c, 20),),
        'ceiling.tool.low': lambda c: (set_first(c, 0),),
        'ceiling.tool.original.low': lambda c: (ModifyCost(c.state.opening.original_entities[c.player_id - 1][
            c.state.players[c.player_id].original_deck.index('ceiling.high')], CostSpec(set_to=0), c.source_id),),
        'ceiling.tool.external': lambda c: (AddCostModifier(c.player_id, CostSpec(set_to=0), c.source_id),),
        'ceiling.tool.add': lambda c: (AddToDeck(c.player_id, 'ceiling.high'),),
        'ceiling.tool.clear': lambda c: (DestroyDeckMatching(c.player_id, count=40, reveal=False),),
        'ceiling.tool.draw': lambda c: (Draw(c.player_id),),
        'ceiling.tool.face': lambda c: (TransformCapturedMinion(
            CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]]), 'ceiling.high'),),
        'ceiling.tool.check': lambda c: (branch(c.player_id),),
        'ceiling.tool.wait': lambda c: (pause(c.player_id), branch(c.player_id)),
        'ceiling.tool.selected': lambda c: (CheckDeckCondition(c.player_id, CEILING,
            (pause(c.player_id), AddToDeck(c.player_id, 'ceiling.high'), GainArmor(c.player_id, 3)),
            (pause(c.player_id), DestroyDeckMatching(c.player_id, count=40, reveal=False), GainArmor(c.player_id, 1))),),
        'ceiling.tool.fail': lambda c: (branch(c.player_id), InvokeBehavior('ceiling.fail', c.source_id, c.player_id)),
        'ceiling.tool.wait.fail': lambda c: (pause(c.player_id), branch(c.player_id), InvokeBehavior('ceiling.fail', c.source_id, c.player_id)),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata(CardClass.MAGE)))
    for cid, fn in (
        ('ceiling.fixture.start', lambda c: (branch(c.player_id),)),
        ('ceiling.fixture.wait.before', lambda c: (pause(c.player_id), branch(c.player_id))),
        ('ceiling.fixture.wait.selected', lambda c: (CheckDeckCondition(c.player_id, CEILING,
            (pause(c.player_id), GainArmor(c.player_id, 3)), (pause(c.player_id), GainArmor(c.player_id, 1))),)),
    ):
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, 'Explicit synthetic opening gate', CardType.MINION, health=1,
            metadata=metadata(), opening_hooks=(OpeningHook('before_deal', cid),)))
    return r


class StartingDeckCostCeilingTests(unittest.TestCase):
    def match(self, extra=(), *, mode='low', other_extra=(), other_mode='low', first=1, finish=True):
        r = registry()
        def cards(mode, prefix):
            if any(cid.startswith('ceiling.tool.') for cid in prefix):
                prefix = ('ceiling.fixture.prepare',) + tuple(prefix)
            return tuple(prefix) + tuple(f'ceiling.{mode}.{i}' for i in range(1, 31 - len(prefix)))
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

    def query(self, g, limit=3, player=1):
        return matches_deck_condition(g.state, g.registry, player, DeckCostCeilingCondition(limit, 'printed'))

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

    def test_complete_raw_pin_is_evidence_and_chef_remains_explicitly_unsupported(self):
        raw, r = evidence(), registry()
        self.assertEqual((raw['id'], raw['cost'], raw['attack'], raw['health']), ('JAIL_860', 3, 3, 3))
        self.assertIn('or less', raw['text_en'])
        self.assertIn('five turns', raw['text_en'])
        self.assertEqual(raw['tags']['CHEF_NETHREK_REQUIREMENT'], 4)
        self.assertNotIn('JAIL_860', r.cards)
        with self.assertRaises(UnsupportedDefinitionError):
            r.card('JAIL_860')

    def test_inclusive_ceiling_is_parameterized_at_and_below_the_bound(self):
        g = self.match(('ceiling.equal',))
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, 2))
        self.assertTrue(self.query(g, 4))

    def test_zero_is_a_valid_printed_cost_and_zero_ceiling(self):
        g = self.match(mode='zero', other_mode='zero')
        self.assertTrue(self.query(g, 0))
        self.assertFalse(self.query(self.match(), 0))

    def test_all_five_deck_card_kinds_and_duplicates_participate(self):
        g = self.match(('ceiling.equal', 'ceiling.equal', 'ceiling.spell', 'ceiling.weapon', 'ceiling.location', 'ceiling.hero'))
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, 2))
        self.assertEqual(len(g.state.players[1].original_deck), 30)

    def test_non_minion_above_limit_fails_and_large_costs_are_not_capped(self):
        for cid in ('ceiling.high.spell', 'ceiling.large'):
            g = self.match((cid,))
            self.assertFalse(self.query(g))
            self.assertTrue(self.query(g, g.registry.card(cid).cost))

    def test_each_player_reads_own_origin_including_second_player_first(self):
        g = self.match(other_extra=('ceiling.high',), first=2)
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, player=2))
        self.assertTrue(self.query(g, 4, 2))

    def test_scenario_and_forged_original_tuple_do_not_supply_constructed_facts(self):
        r = registry()
        g = Game.from_scenario(Scenario((PlayerSetup('mage.hero', deck=('ceiling.low.1',)), PlayerSetup('warrior.hero'))), r)
        for forge in (False, True):
            state = g.state
            if forge:
                state.players[1].original_deck = ('ceiling.low.1',)
            with self.assertRaises(UnknownDeckFacts):
                matches_deck_condition(state, r, 1, CEILING)

    def test_host_cost_operand_needs_no_unrelated_identity_metadata(self):
        g = self.match()
        state = g.state
        state.players[1].original_deck = ('ceiling.no.meta',)
        self.assertTrue(matches_deck_condition(state, g.registry, 1, CEILING))
        with self.assertRaises(UnknownDeckFacts):
            matches_deck_condition(state, g.registry, 1, DeckCondition('starting'))

    def test_empty_universal_host_operand_is_not_claimed_as_legal_native_match(self):
        g = self.match()
        state = g.state
        state.players[1].original_deck = ()
        self.assertTrue(matches_deck_condition(state, g.registry, 1, CEILING))

    def test_earlier_above_limit_does_not_hide_later_unknown_definition(self):
        g = self.match()
        state = g.state
        state.players[1].original_deck = ('ceiling.high', 'unknown.ceiling.card')
        with self.assertRaises(UnsupportedDefinitionError):
            matches_deck_condition(state, g.registry, 1, CEILING)

    def test_query_is_pure_for_rng_events_history_actions_and_origins(self):
        g = self.match(('ceiling.equal',))
        saved = g.snapshot()
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, 2))
        self.assertEqual(g.snapshot(), saved)

    def test_full_mulligan_and_coin_do_not_rewrite_original_cost_ceiling(self):
        g = self.match(('ceiling.equal',), finish=False)
        while g.state.pending_choice:
            self.choose(g, tuple(o.id for o in g.state.pending_choice.options))
        self.assertTrue(self.query(g))
        self.assertEqual(tuple(map(len, g.state.opening.original_entities)), (30, 30))
        self.assertIn('coin', [g.state.entities[i].card_id for i in g.state.players[2].hand])
        self.portable(g)

    def test_real_saved_fee_above_limit_does_not_change_original_printed_cost(self):
        g = self.match(('ceiling.tool.high',))
        self.play(g, 'ceiling.tool.high')
        entity = g.state.entities[g.state.players[1].deck[0]]
        self.assertEqual(local_cost(entity)[0], 20)
        self.assertLessEqual(g.registry.card(entity.card_id).cost, 3)
        self.assertTrue(self.query(g))
        self.portable(g)

    def test_lowering_saved_fee_cannot_fix_an_original_above_limit_card(self):
        g = self.match(('ceiling.high', 'ceiling.tool.original.low', 'ceiling.tool.clear'))
        identity = g.state.opening.original_entities[0][g.state.players[1].original_deck.index('ceiling.high')]
        self.play(g, 'ceiling.tool.original.low')
        self.assertEqual(local_cost(g.state.entities[identity])[0], 0)
        self.assertFalse(self.query(g))
        self.play(g, 'ceiling.tool.clear')
        self.assertEqual(g.state.players[1].deck, [])
        self.assertFalse(self.query(g))

    def test_external_hand_quote_does_not_substitute_original_printed_basis(self):
        g = self.match(('ceiling.high', 'ceiling.tool.external'))
        self.play(g, 'ceiling.tool.external')
        entity = g.state.entities[g.state.players[1].deck[0]]
        self.assertEqual(quote_cost(g.state, g.registry, entity).amount, 0)
        self.assertFalse(self.query(g))

    def test_generated_above_limit_card_is_current_only(self):
        g = self.match(('ceiling.tool.add',))
        self.play(g, 'ceiling.tool.add')
        self.assertIn('ceiling.high', [g.state.entities[i].card_id for i in g.state.players[1].deck])
        self.assertNotIn('ceiling.high', g.state.players[1].original_deck)
        self.assertTrue(self.query(g))

    def test_real_face_change_and_draw_do_not_rewrite_origin(self):
        g = self.match(('ceiling.tool.face', 'ceiling.tool.draw'))
        identity = g.state.players[1].deck[0]
        self.play(g, 'ceiling.tool.face')
        self.assertEqual(g.state.entities[identity].card_id, 'ceiling.high')
        self.play(g, 'ceiling.tool.draw')
        self.assertIn(identity, g.state.players[1].hand)
        self.assertTrue(self.query(g))

    def test_natural_turns_keep_original_ceiling(self):
        g = self.match(('ceiling.high',))
        original = g.state.players[1].original_deck
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertEqual(g.state.players[1].original_deck, original)
        self.assertFalse(self.query(g))
        self.portable(g)

    def test_synthetic_before_deal_gate_uses_original_bound_for_both_results(self):
        g = self.match(('ceiling.fixture.start',), other_extra=('ceiling.fixture.start', 'ceiling.high'), finish=False)
        self.assertEqual((self.armor(g), self.armor(g, 2)), (3, 1))
        self.assertEqual([len(g.state.players[p].hand) for p in (1, 2)], [3, 4])
        self.finish(g)
        self.portable(g)

    def test_player_command_executes_synthetic_branch_once(self):
        g = self.match(('ceiling.tool.check',))
        port = g.for_player(1)
        dto = port.legal_actions()
        ref = next(row['ref'] for row in g.observe(1)['players'][0]['hand'] if row['card_id'] == 'ceiling.tool.check')
        action = next(row for row in dto['actions'] if row.get('card') == ref)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((self.armor(g), g.state.players[1].mana), (3, 10))
        self.assertEqual(len(g.state.play_history), 1)

    def test_opening_unexecuted_ceiling_recovers_then_mulligan_continues(self):
        g = self.match(('ceiling.fixture.wait.before',), finish=False)
        restored = self.portable(g)
        self.finish(g)
        self.finish(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(self.armor(g), 3)

    def test_opening_selected_both_branches_resume_on_independent_registry(self):
        for extra, armor in (((), 3), (('ceiling.high',), 1)):
            g = self.match(('ceiling.fixture.wait.selected',) + extra, finish=False)
            restored = self.portable(g)
            self.finish(g)
            self.finish(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(self.armor(g), armor)

    def test_unexecuted_play_gate_recovers_for_original_success_and_failure(self):
        for extra, armor in (((), 3), (('ceiling.high',), 1)):
            g = self.match(('ceiling.tool.wait',) + extra)
            self.play(g, 'ceiling.tool.wait')
            restored = self.portable(g)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(self.armor(g), armor)

    def test_selected_branch_is_not_rechosen_after_current_deck_changes(self):
        for extra, armor in (((), 3), (('ceiling.high',), 1)):
            g = self.match(('ceiling.tool.selected',) + extra)
            self.play(g, 'ceiling.tool.selected')
            restored = self.portable(g)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(self.armor(g), armor)
            self.assertEqual(self.query(g), armor == 3)

    def test_failure_rolls_back_entire_action_and_waiting_continuation(self):
        for cid in ('ceiling.tool.fail', 'ceiling.tool.wait.fail'):
            g = self.match((cid,))
            if cid.endswith('wait.fail'):
                self.play(g, cid)
            before = g.snapshot()
            with self.assertRaises(ResolutionError):
                self.choose(g) if cid.endswith('wait.fail') else self.play(g, cid)
            self.assertEqual(g.snapshot(), before)

    def test_new_three_field_payload_and_all_original_declarations_roundtrip(self):
        g = self.match()
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        declarations = ((CEILING, {'cost_limit', 'cost_basis', 'scope'}),
            (DeckCondition(), {'scope', 'predicate'}), (DeckCostCondition(4, 'local'), {'cost', 'cost_basis', 'scope'}),
            (DeckSpellSchoolCondition(SpellSchool.SHADOW), {'spell_school', 'scope'}),
            (DeckMinionCostCondition(4, 'less', 'local'), {'cost', 'comparison', 'cost_basis', 'scope'}))
        for declaration, fields in declarations:
            wire = codec.encode(declaration)
            self.assertEqual(codec.decode(wire), declaration)
            self.assertEqual(set(wire['fields']), fields)
            for field in fields:
                bad = deepcopy(wire)
                del bad['fields'][field]
                with self.assertRaises(ValueError):
                    codec.decode(bad)

    def test_declaration_has_strict_explicit_printed_starting_policy(self):
        cases = [(value, 'printed', 'starting') for value in (True, -1, 3.0, '3', None)]
        cases += [(3, value, 'starting') for value in (True, None, 'local', 'external', '')]
        cases += [(3, 'printed', value) for value in (True, None, 'current', 'hand', '')]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                DeckCostCeilingCondition(*args)
        with self.assertRaises(TypeError):
            DeckCostCeilingCondition(3)
        with self.assertRaises(ValueError):
            DeckCondition('starting', 'all_cost_at_most')

    def test_waiting_snapshot_rejects_bad_limits_basis_scope_and_extra_fields(self):
        g = self.match(('ceiling.tool.wait',))
        self.play(g, 'ceiling.tool.wait')
        for field, value in (('cost_limit', True), ('cost_limit', -1), ('cost_basis', 'local'), ('scope', 'current'), ('invented', 1)):
            saved = g.snapshot()
            self.nested(saved['resolution_frame'], 'DeckCostCeilingCondition')['fields'][field] = value
            self.reject(saved)

    def test_rehashed_constructed_origin_tampering_remains_rejected(self):
        g = self.match()
        saved = g.snapshot()
        saved['state']['players']['1']['original_deck'][0] = 'ceiling.high'
        self.reject(saved)

    def test_player_projections_hide_origin_costs_and_private_gate_frames(self):
        g = self.match(('ceiling.fixture.wait.before',), finish=False)
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player)) + json.dumps(g.for_player(player).legal_actions())
            for private in ('DeckCostCeilingCondition', 'cost_limit', 'cost_basis', 'original_deck', 'resolution_frame', 'ceiling.low.1'):
                self.assertNotIn(private, text)

    def test_persistent_wire_layout_stays_and_previous_handler_is_rejected(self):
        g = self.match()
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version), (SNAPSHOT_SCHEMA_VERSION, 'prototype-v302', CORE_EFFECTS_VERSION))
        saved = g.snapshot()
        saved['mechanics_version']['version'] = 'core-effects-v233'
        self.reject(saved)


if __name__ == '__main__':
    unittest.main()
