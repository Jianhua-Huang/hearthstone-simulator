"""Original no-SPELL facts via the existing two-field deck condition."""
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
    UnknownDeckFacts, Zone, matches_deck_condition)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption,
    Draw, GainArmor, InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from test_current_deck_empty_basics import rehash
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT/'data/support/starting-deck-no-spells-basics.json'
PIN = '132f56f858e3d9916cb1bab0b5eb3c823173f1aadcb9aa898cd0338153014dc3'
NO_SPELLS = DeckCondition('starting', 'no_spells')


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or [r['id'] for r in packet['records']] != ['JAIL_806']:
        raise ValueError('Complete starting no-spells evidence changed')
    row = packet['records'][0]
    if canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Complete original card row changed')
    return row['data']


def pause(player):
    return RequestChoice(player, (ChoiceOption('ok', 'Continue', ()),))


def branch(player):
    return CheckDeckCondition(player, NO_SPELLS, (GainArmor(player, 3),), (GainArmor(player, 1),))


def registry():
    evidence()
    r = opening_registry()
    for i in range(1, 31):
        r.register_card(CardDefinition(f'nost.minion.{i}', 'Experimental original nonspell slot',
            CardType.MINION, cost=1, health=2, metadata=metadata()))
    r.register_behavior('nost.nop', lambda c: ())
    for cid, kind, cost, fields in (
        ('nost.spell', CardType.SPELL, 0, {'spell_school': SpellSchool.SHADOW}),
        ('nost.schoolless', CardType.SPELL, 0, {}),
        ('nost.large.spell', CardType.SPELL, 101, {'spell_school': SpellSchool.ARCANE}),
        ('nost.weapon', CardType.WEAPON, 1, {'attack': 1, 'durability': 1}),
        ('nost.location', CardType.LOCATION, 1, {'durability': 1, 'on_use': 'nost.nop'}),
        ('nost.hero', CardType.HERO, 1, {'health': 30, 'hero_card': True,
            'initial_hero_power': 'mage.power', 'on_play': 'nost.nop'}),
    ):
        r.register_card(CardDefinition(cid, cid, kind, cost=cost,
            metadata=metadata(CardClass.MAGE if kind == CardType.HERO else CardClass.NEUTRAL), **fields))
    r.register_card(CardDefinition('nost.unreviewed.minion', 'Diagnostic known MINION without identity metadata',
        CardType.MINION, health=1))
    r.register_card(CardDefinition('nost.unreviewed.spell', 'Diagnostic known SPELL without identity metadata', CardType.SPELL))

    def prepare(c):
        return (ChangeManaCrystals(c.player_id, 9), *(AddToHand(c.player_id, cid)
            for cid in c.state.players[c.player_id].original_deck if cid.startswith('nost.tool.')))
    r.register_behavior('nost.prepare', prepare)
    r.register_card(CardDefinition('nost.fixture.prepare', 'Explicit experimental hand preparation',
        CardType.MINION, health=1, metadata=metadata(),
        opening_hooks=(OpeningHook('after_mulligan', 'nost.prepare'),)))

    def original(c, cid):
        identity = c.state.opening.original_entities[c.player_id-1][c.state.players[c.player_id].original_deck.index(cid)]
        return c.state.entities[identity]

    def fail(c):
        raise ResolutionError('Expected late starting no-spells branch failure')
    r.register_behavior('nost.fail', fail)
    scripts = {
        'nost.tool.add': lambda c: (AddToDeck(c.player_id, 'nost.spell'), AddToHand(c.player_id, 'nost.spell')),
        'nost.tool.draw': lambda c: (Draw(c.player_id),),
        'nost.tool.clear': lambda c: (DestroyDeckMatching(c.player_id, count=40, reveal=False),),
        'nost.tool.remove.original': lambda c: (RemoveFromGame((CardReference.capture(original(c, 'nost.spell')),), c.source_id),),
        'nost.tool.local': lambda c: (ModifyCost(original(c, 'nost.minion.1').id, CostSpec(set_to=20), c.source_id),),
        'nost.tool.face': lambda c: (TransformCapturedMinion(CardReference.capture(original(c, 'nost.minion.1')), 'nost.minion.2'),),
        'nost.tool.check': lambda c: (branch(c.player_id),),
        'nost.tool.wait': lambda c: (pause(c.player_id), branch(c.player_id)),
        'nost.tool.selected': lambda c: (CheckDeckCondition(c.player_id, NO_SPELLS,
            (pause(c.player_id), AddToDeck(c.player_id, 'nost.spell'), GainArmor(c.player_id, 3)),
            (pause(c.player_id), DestroyDeckMatching(c.player_id, count=40, reveal=False), GainArmor(c.player_id, 1))),),
        'nost.tool.fail': lambda c: (branch(c.player_id), InvokeBehavior('nost.fail', c.source_id, c.player_id)),
        'nost.tool.wait.fail': lambda c: (pause(c.player_id), branch(c.player_id), InvokeBehavior('nost.fail', c.source_id, c.player_id)),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        # MINION instrumentation keeps the true original no-SPELL branch reachable.
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=1, battlecry=cid, metadata=metadata()))
    for cid, fn in (
        ('nost.fixture.start', lambda c: (branch(c.player_id),)),
        ('nost.fixture.wait.before', lambda c: (pause(c.player_id), branch(c.player_id))),
        ('nost.fixture.wait.selected', lambda c: (CheckDeckCondition(c.player_id, NO_SPELLS,
            (pause(c.player_id), GainArmor(c.player_id, 3)), (pause(c.player_id), GainArmor(c.player_id, 1))),)),
    ):
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, 'Explicit synthetic opening gate', CardType.MINION,
            health=1, metadata=metadata(), opening_hooks=(OpeningHook('before_deal', cid),)))
    return r


class StartingDeckNoSpellsTests(unittest.TestCase):
    def match(self, extra=(), *, other_extra=(), first=1, finish=True):
        r = registry()
        def cards(prefix):
            if any(cid.startswith('nost.tool.') for cid in prefix):
                prefix = ('nost.fixture.prepare',) + tuple(prefix)
            return tuple(prefix) + tuple(f'nost.minion.{i}' for i in range(1, 31-len(prefix)))
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

    def query(self, g, player=1):
        return matches_deck_condition(g.state, g.registry, player, NO_SPELLS)

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

    def test_complete_raw_requires_starting_no_spells_without_partial_native_adapter(self):
        packet, raw, r = json.loads(SUPPORT.read_bytes()), evidence(), registry()
        self.assertEqual(hashlib.sha256((ROOT/'data/extracted/cards.json').read_bytes()).hexdigest(), packet['source_sha256'])
        self.assertEqual((raw['id'], raw['cost'], raw['attack'], raw['health']), ('JAIL_806', 6, 6, 6))
        self.assertIn('deck started with no', raw['text_en'])
        self.assertIn('spells', raw['text_en'])
        with self.assertRaises(UnsupportedDefinitionError):
            r.card('JAIL_806')

    def test_real_thirty_slot_nonspell_deck_passes_and_every_spell_cost_or_school_fails(self):
        self.assertTrue(self.query(self.match()))
        for cid in ('nost.spell', 'nost.schoolless', 'nost.large.spell'):
            self.assertFalse(self.query(self.match((cid,))))

    def test_other_constructed_types_are_nonspells_and_duplicates_do_not_hide_spells(self):
        self.assertTrue(self.query(self.match(('nost.weapon', 'nost.location', 'nost.hero'))))
        self.assertFalse(self.query(self.match(('nost.spell', 'nost.spell'))))

    def test_absence_differs_from_all_shadow_spells_and_current_no_minions(self):
        g = self.match(('nost.spell',))
        self.assertTrue(matches_deck_condition(g.state, g.registry, 1, DeckSpellSchoolCondition(SpellSchool.SHADOW)))
        self.assertFalse(self.query(g))
        g = self.match()
        self.assertTrue(self.query(g))
        self.assertFalse(matches_deck_condition(g.state, g.registry, 1, DeckCondition('current', 'no_minions')))

    def test_current_scenario_and_forged_original_tuple_do_not_supply_starting_facts(self):
        r = registry()
        current = tuple(f'nost.minion.{i}' for i in range(1, 31))
        g = Game.from_scenario(Scenario((PlayerSetup('mage.hero', deck=current), PlayerSetup('warrior.hero'))), r)
        for forge in (False, True):
            if forge:
                g.state.players[1].original_deck = current
            with self.assertRaises(UnknownDeckFacts):
                self.query(g)

    def test_both_players_read_own_origin_when_second_player_starts(self):
        g = self.match(other_extra=('nost.spell',), first=2)
        self.assertTrue(self.query(g, 1))
        self.assertFalse(self.query(g, 2))

    def test_host_diagnostics_need_no_identity_metadata_and_reject_all_late_unknown_rows(self):
        # Detached diagnostic operands are not advertised as valid native games.
        g = self.match()
        state = deepcopy(g.state)
        for cid, answer in (('nost.unreviewed.minion', True), ('nost.unreviewed.spell', False)):
            state.players[1].original_deck = (cid,)
            self.assertEqual(matches_deck_condition(state, g.registry, 1, NO_SPELLS), answer)
            state.players[1].original_deck = (cid, 'unknown.nost.definition')
            with self.assertRaises(UnsupportedDefinitionError):
                matches_deck_condition(state, g.registry, 1, NO_SPELLS)

    def test_pure_query_preserves_rng_events_history_actions_and_origins(self):
        for extra in ((), ('nost.spell',)):
            g = self.match(extra)
            before, actions = g.snapshot(), g.legal_actions()
            self.query(g)
            self.assertEqual(g.snapshot(), before)
            self.assertEqual(g.legal_actions(), actions)

    def test_full_mulligan_and_coin_keep_starting_type_facts(self):
        g = self.match(finish=False)
        while g.state.pending_choice:
            self.choose(g, tuple(o.id for o in g.state.pending_choice.options))
        self.assertTrue(self.query(g))
        self.assertIn('coin', [g.state.entities[i].card_id for i in g.state.players[2].hand])
        self.assertTrue(self.query(g, 2))
        self.portable(g)

    def test_generated_spells_in_hand_and_deck_do_not_rewrite_original_absence(self):
        g = self.match(('nost.tool.add',))
        self.play(g, 'nost.tool.add')
        self.assertIn('nost.spell', [g.state.entities[i].card_id for i in g.state.players[1].deck])
        self.assertIn('nost.spell', [g.state.entities[i].card_id for i in g.state.players[1].hand])
        self.assertTrue(self.query(g))
        self.portable(g)

    def test_original_spell_removed_from_game_still_prevents_starting_absence(self):
        g = self.match(('nost.spell', 'nost.tool.remove.original'))
        identity = g.state.opening.original_entities[0][g.state.players[1].original_deck.index('nost.spell')]
        self.play(g, 'nost.tool.remove.original')
        self.assertEqual(g.state.entities[identity].zone, Zone.SETASIDE)
        self.assertFalse(self.query(g))
        self.portable(g)

    def test_draw_and_clear_current_deck_do_not_make_original_spell_deck_pass(self):
        g = self.match(('nost.spell', 'nost.tool.draw', 'nost.tool.clear'))
        for cid in ('nost.tool.draw', 'nost.tool.clear'):
            self.play(g, cid)
            self.assertFalse(self.query(g))
        self.assertEqual(g.state.players[1].deck, [])
        self.portable(g)

    def test_cost_and_stored_minion_face_changes_preserve_original_kind_facts(self):
        g = self.match(('nost.tool.local', 'nost.tool.face'))
        identity = g.state.opening.original_entities[0][g.state.players[1].original_deck.index('nost.minion.1')]
        self.play(g, 'nost.tool.local')
        self.assertEqual(local_cost(g.state.entities[identity])[0], 20)
        self.assertTrue(self.query(g))
        self.play(g, 'nost.tool.face')
        self.assertEqual(g.state.entities[identity].card_id, 'nost.minion.2')
        self.assertTrue(self.query(g))
        self.portable(g)

    def test_natural_turns_keep_original_facts_for_both_results(self):
        g = self.match(other_extra=('nost.spell',))
        for _ in range(4):
            g.apply(EndTurn(g.state.active_player))
            self.assertTrue(self.query(g, 1))
            self.assertFalse(self.query(g, 2))
        self.portable(g)

    def test_before_deal_gate_uses_original_types_for_each_player(self):
        g = self.match(('nost.fixture.start',), other_extra=('nost.fixture.start', 'nost.spell'), finish=False)
        self.assertEqual((self.armor(g), self.armor(g, 2)), (3, 1))
        self.finish(g)
        self.portable(g)

    def test_player_command_runs_one_original_condition_branch(self):
        g = self.match(('nost.tool.check',))
        port = g.for_player(1)
        dto = port.legal_actions()
        ref = next(row['ref'] for row in g.observe(1)['players'][0]['hand'] if row['card_id'] == 'nost.tool.check')
        action = next(row for row in dto['actions'] if row.get('card') == ref)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((self.armor(g), g.state.players[1].mana, len(g.state.play_history)), (3, 10, 1))

    def test_opening_unexecuted_and_selected_gates_resume_portably(self):
        for fixture in ('nost.fixture.wait.before', 'nost.fixture.wait.selected'):
            for extra, armor in (((), 3), (('nost.spell',), 1)):
                g = self.match((fixture,) + extra, finish=False)
                restored = self.portable(g)
                self.finish(g)
                self.finish(restored)
                self.assertEqual(g.snapshot(), restored.snapshot())
                self.assertEqual(self.armor(g), armor)

    def test_unexecuted_play_gate_resumes_for_both_original_results(self):
        for extra, armor in (((), 3), (('nost.spell',), 1)):
            g = self.match(('nost.tool.wait',) + extra)
            self.play(g, 'nost.tool.wait')
            restored = self.portable(g)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(self.armor(g), armor)

    def test_selected_branch_keeps_its_sequence_after_wait_and_current_deck_changes(self):
        for extra, armor in (((), 3), (('nost.spell',), 1)):
            g = self.match(('nost.tool.selected',) + extra)
            self.play(g, 'nost.tool.selected')
            restored = self.portable(g)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(self.armor(g), armor)
            self.assertEqual(self.query(g), armor == 3)

    def test_late_action_and_choice_failures_roll_back_all_effects(self):
        for cid in ('nost.tool.fail', 'nost.tool.wait.fail'):
            g = self.match((cid,))
            if cid.endswith('wait.fail'):
                self.play(g, cid)
            before = g.snapshot()
            with self.assertRaises(ResolutionError):
                self.choose(g) if cid.endswith('wait.fail') else self.play(g, cid)
            self.assertEqual(g.snapshot(), before)

    def test_same_two_field_payload_and_old_other_conditions_roundtrip(self):
        g = self.match()
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        declarations = (NO_SPELLS, DeckCondition(), DeckCostCondition(4, 'local'),
            DeckSpellSchoolCondition(SpellSchool.SHADOW), DeckMinionCostCondition(4, 'less', 'local'),
            DeckCostCeilingCondition(3, 'printed'), DeckMinionCostSumCondition(100, 'printed'), DeckCostDiversityCondition(10, 'printed'))
        for declaration in declarations:
            wire = codec.encode(declaration)
            self.assertEqual(codec.decode(wire), declaration)
        self.assertEqual(set(codec.encode(NO_SPELLS)['fields']), {'scope', 'predicate'})
        self.assertEqual(set(codec.encode(branch(1))['fields']), {'player_id', 'condition', 'on_match', 'on_miss'})

    def test_declaration_rejects_current_scope_boolean_values_and_unknown_predicates(self):
        for args in (('current', 'no_spells'), ('hand', 'no_spells'), (True, 'no_spells'),
                ('starting', True), ('starting', 'no_unknown_types'), ('starting', 'no_minions')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                DeckCondition(*args)

    def test_waiting_snapshot_rejects_illegal_scope_predicate_extra_fields_and_player(self):
        g = self.match(('nost.tool.wait',))
        self.play(g, 'nost.tool.wait')
        for field, value in (('scope', 'current'), ('scope', True), ('predicate', True), ('predicate', 'always'), ('invented', 1)):
            saved = g.snapshot()
            self.nested(saved['resolution_frame'], 'DeckCondition')['fields'][field] = value
            self.reject(saved)
        saved = g.snapshot()
        self.nested(saved['resolution_frame'], 'CheckDeckCondition')['fields']['player_id'] = True
        self.reject(saved)

    def test_rehashed_constructed_origin_tampering_remains_rejected(self):
        g = self.match()
        saved = g.snapshot()
        saved['state']['players']['1']['original_deck'][0] = 'nost.spell'
        self.reject(saved)

    def test_player_projections_hide_original_type_inventory_and_private_condition(self):
        g = self.match(('nost.fixture.wait.before', 'nost.spell'), finish=False)
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player)) + json.dumps(g.for_player(player).legal_actions())
            for private in ('DeckCondition', 'no_spells', 'original_deck', 'resolution_frame', 'nost.spell'):
                self.assertNotIn(private, text)

    def test_persistent_layout_stays_and_previous_handler_and_schema_are_rejected(self):
        g = self.match()
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version),
            (265, 'prototype-v302', CORE_EFFECTS_VERSION))
        saved = g.snapshot()
        saved['mechanics_version']['version'] = 'core-effects-v237'
        self.reject(saved)
        saved = g.snapshot()
        saved['schema_version'] = 215
        self.reject(saved)
