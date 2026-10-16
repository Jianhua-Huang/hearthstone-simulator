"""Distinct personally cast schools use the original spell cost/history pipeline."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CastWhenDrawnSpec, EndTurn,
    Game, IllegalAction, PlayCard, PlayerSetup, PlayerSpellCountCostSpec, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact, capture_quote_fact,
    quote_generated_cost)
from hs_sim.engine.effects import AddToHand, ChoiceOption, Draw, InvokeBehavior, RequestChoice
from hs_sim.engine.intrinsic_costs import validate_intrinsic_history_prefix, validate_intrinsic_stage_fact
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell, cast_spells
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
import test_player_spell_count_cost_basics as old
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

WISDOM = 'TTN_085'
PROFILE = 'cost.player-distinct-spell-school-count-v1'
PATH = Path(__file__).resolve().parents[1] / 'data/support/player-spell-school-cost-basics.json'
PIN = '3e5b8c62504eade691be76949af7e1585c56fe0504b0de6e7cce28b4d7cae64c'


def evidence():
    support = json.loads(PATH.read_bytes())
    if canonical_digest(support) != PIN:
        raise ValueError('Distinct-school complete evidence changed')
    for row in support['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Distinct-school original row changed')
    return {row['id']: row['data'] for row in support['records']}


def registry(*, committed_wait=False, payload_wait=False):
    r = old.registry()
    row = evidence()[WISDOM]
    r.register_behavior('schools.wisdom', lambda c: (Draw(c.player_id, 2, source_id=c.source_id),))
    r.register_card(CardDefinition(WISDOM, row['name'], CardType.SPELL, cost=row['cost'],
        on_play='schools.wisdom', spell_school=SpellSchool.ARCANE,
        metadata=metadata(CardClass.MAGE, rarity=Rarity.EPIC),
        player_spell_count_cost=PlayerSpellCountCostSpec(PROFILE)))
    for school in SpellSchool:
        cid = 'schools.' + school.value
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play='count.noop',
            spell_school=school, metadata=metadata()))
    r.register_card(CardDefinition('schools.fire.two', 'Second printed Fire face', CardType.SPELL,
        on_play='count.noop', spell_school=SpellSchool.FIRE, metadata=metadata()))
    r.register_card(CardDefinition('schools.none', 'Explicit unschooled spell', CardType.SPELL,
        on_play='count.noop', metadata=metadata()))
    r.register_card(CardDefinition('schools.wait', 'Accepted personal cast waiting for completion', CardType.SPELL,
        on_play='count.wait', spell_school=SpellSchool.FEL, metadata=metadata()))
    r.register_card(CardDefinition('schools.drawn', 'Existing automatic draw source', CardType.SPELL,
        on_play='count.noop', spell_school=SpellSchool.SHADOW,
        keywords=(old.Keyword.CASTS_WHEN_DRAWN,), cast_when_drawn=CastWhenDrawnSpec(replacement=False), metadata=metadata()))
    scripts = {
        'schools.auto': lambda c: (CastSpell(c.player_id, 'schools.frost', c.source_id),),
        'schools.history': lambda c: (RecastSpell(player_id=c.player_id, cast_id=c.state.cast_history[0].id, source_id=c.source_id),),
        'schools.acquire': lambda c: (AddToHand(c.player_id, WISDOM),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=2, battlecry=cid, metadata=metadata()))
    r.register_behavior('schools.refill', lambda c: (AddToHand(c.player_id, 'schools.refill'),))
    r.register_card(CardDefinition('schools.refill', 'Repeatedly acquired physical Fire faces', CardType.SPELL,
        on_play='schools.refill', spell_school=SpellSchool.FIRE, metadata=metadata()))
    r.register_behavior('schools.fail', lambda c: (AddToHand(c.player_id, 'schools.fire'),
                                                 AddToHand(c.player_id, 'missing.school.fixture')))

    def pause(c):
        applies = (c.state.entities[c.event.source_id].card_id == WISDOM if c.event.kind == 'card_committed'
                   else c.event.player_id == c.player_id and len(c.state.draw_history) == 1)
        if not applies:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue original paid spell'),
            ChoiceOption('fault', 'Verify original transaction rollback',
                (InvokeBehavior('schools.fail', c.source_id, c.player_id),)),
        ), c.source_id),)

    for flag, event in ((committed_wait, 'card_committed'), (payload_wait, 'card_drawn')):
        if flag:
            cid = 'schools.watch.' + event
            r.register_behavior(cid, pause)
            r.register_card(CardDefinition(cid, cid, CardType.MINION, health=3,
                triggers=(TriggerSpec(event, cid),), metadata=metadata()))
    return r


class PlayerSpellSchoolCostTests(unittest.TestCase):
    def setUp(self):
        self.options = {}

    def game(self, hand=(WISDOM,), *, deck=('card.1', 'card.2', 'card.3'), enemy_hand=(), board=(), enemy_board=(), mana=10):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=hand, deck=deck, board=board, mana=mana, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.4',)*3, mana=10, max_mana=10)), seed=53), registry(**self.options))

    def source(self, g, cid=WISDOM, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)

    def fact(self, g, cid=WISDOM, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))

    def price(self, g, cid=WISDOM, player=1):
        return self.fact(g, cid, player).amount

    def play(self, g, cid, player=None):
        player = g.state.active_player if player is None else player
        eid = self.source(g, cid, player).id
        g.apply(PlayCard(player, eid))
        return eid

    def choose(self, g, option='continue'):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry(**self.options))
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(**self.options)).snapshot(), saved)
        for player in (1, 2):
            self.assertEqual(restored.observe(player), g.observe(player))
        return restored

    def two_fire(self, **kwargs):
        g = self.game(hand=(WISDOM, 'schools.fire', 'schools.fire.two', *kwargs.pop('extras', ())), **kwargs)
        self.play(g, 'schools.fire')
        self.play(g, 'schools.fire.two')
        return g

    def test_complete_raw_and_necessary_five_mana_epic_arcane_draw_two_adapter(self):
        row = evidence()[WISDOM]
        original = next(r for r in json.loads((PATH.parents[1]/'extracted/cards.json').read_bytes()) if r['id'] == WISDOM)
        self.assertEqual(row, original)
        g = self.game()
        native = g.registry.card(WISDOM)
        self.assertEqual((native.cost, native.kind, native.spell_school, native.metadata.rarity),
            (5, CardType.SPELL, SpellSchool.ARCANE, Rarity.EPIC))
        self.assertEqual((row['tags']['CLASS'], row['tags']['RARITY'], row['tags']['SPELL_SCHOOL']), (4, 4, 1))
        self.play(g, WISDOM)
        self.assertEqual([g.state.entities[eid].card_id for eid in g.state.players[1].hand], ['card.1', 'card.2'])
        self.assertEqual(len(g.state.draw_history), 2)
        self.portable(g)

    def test_finite_profiles_preserve_old_minion_kind_and_reject_arbitrary_policy(self):
        for profile in (None, True, 'all.automatic', 'all.attempts', 'formula'):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                PlayerSpellCountCostSpec(profile)
        r = registry()
        for native in (replace(r.card(WISDOM), id='bad.kind', kind=CardType.MINION, health=2),
                       replace(r.card(old.ARCANE), id='bad.kind.old', kind=CardType.SPELL, health=0)):
            with self.subTest(card=native.id), self.assertRaises(ValueError):
                r.register_card(native)

    def test_empty_prefix_is_zero_and_ordinary_cards_have_no_stage(self):
        g = self.game(hand=(WISDOM, 'card.1'))
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.rows, f.quantity, f.before, f.after), ((), 0, 5, 5))
        self.assertIsNone(self.fact(g, 'card.1').intrinsic.player_spells)
        self.portable(g)

    def test_two_different_faces_of_one_school_count_once(self):
        g = self.two_fire()
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.cast_history_length, f.quantity, f.after), (2, 1, 4))
        self.assertEqual([r.spell_school for r in f.rows], [SpellSchool.FIRE, SpellSchool.FIRE])
        self.assertNotEqual(f.rows[0].source_id, f.rows[1].source_id)
        self.portable(g)

    def test_frost_fire_and_arcane_are_three_distinct_inputs(self):
        g = self.two_fire(extras=('schools.frost', 'schools.arcane'))
        self.play(g, 'schools.frost')
        self.play(g, 'schools.arcane')
        self.assertEqual((self.fact(g).intrinsic.player_spells.quantity, self.price(g)), (3, 2))
        self.portable(g)

    def test_seven_schools_reach_zero_floor_with_one_zero_mana_payment(self):
        g = self.game(hand=(WISDOM, *('schools.'+s.value for s in SpellSchool)), mana=0)
        for school in SpellSchool:
            self.play(g, 'schools.'+school.value)
        self.assertEqual((self.fact(g).intrinsic.player_spells.quantity, self.price(g)), (7, 0))
        self.play(g, WISDOM)
        root = g.state.play_history[-1]
        self.assertEqual((root.cost, root.submitted_cost.quote.intrinsic.player_spells.quantity, g.state.players[1].mana), (0, 7, 0))
        self.portable(g)

    def test_explicit_unschooled_spells_are_retained_without_new_school(self):
        g = self.game(hand=(WISDOM, 'schools.none', 'schools.fire'))
        self.play(g, 'schools.none')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_spells.rows[0].spell_school), (5, None))
        self.play(g, 'schools.fire')
        self.assertEqual((len(self.fact(g).intrinsic.player_spells.rows), self.price(g)), (2, 4))
        self.portable(g)

    def test_old_root_quantity_remains_distinct_from_unique_school_quantity(self):
        g = self.two_fire(extras=(old.ARCANE,))
        self.assertEqual((self.fact(g).intrinsic.player_spells.quantity, self.fact(g, old.ARCANE).intrinsic.player_spells.quantity), (1, 2))
        self.assertEqual((self.price(g), self.price(g, old.ARCANE)), (4, 10))
        self.portable(g)

    def test_original_registry_school_survives_later_physical_face_change(self):
        g = self.two_fire()
        stage = self.fact(g).intrinsic
        material = g.state.entities[g.state.cast_history[0].source_id]
        state = g.state
        state.entities[material.id].card_id = 'schools.frost'
        # Quotes read the frozen cast card_id, not today's physical face.
        f = capture_quote_fact(state, g.registry, capture_cost_input(state.entities[self.source(g).id])).intrinsic.player_spells
        self.assertEqual((f.quantity, f.rows[0].spell_school, f.after), (1, SpellSchool.FIRE, 4))
        validate_intrinsic_history_prefix(stage, state, g.registry)

    def test_other_player_schools_do_not_enter_the_payers_set(self):
        g = self.game(hand=(WISDOM, 'schools.fire'), enemy_hand=(WISDOM, 'schools.frost'))
        self.play(g, 'schools.fire')
        g.apply(EndTurn(1))
        self.play(g, 'schools.frost')
        self.assertEqual((self.price(g), self.price(g, player=2)), (4, 4))
        self.assertEqual(len(self.fact(g).intrinsic.player_spells.rows), 2)
        self.portable(g)

    def test_countered_school_is_preserved_but_does_not_match(self):
        g = self.game(hand=(WISDOM, 'schools.fire'), enemy_board=('count.counter',))
        self.play(g, 'schools.fire')
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.rows[0].spell_school, f.rows[0].failure, f.quantity, f.after), (SpellSchool.FIRE, 'countered', 0, 5))
        self.portable(g)

    def test_effect_draw_and_history_casts_do_not_add_personal_schools(self):
        g = self.game(hand=(WISDOM, 'schools.fire', 'schools.auto', 'schools.history', 'count.draw'),
            deck=('schools.drawn', 'card.1', 'card.2'))
        for cid in ('schools.fire', 'schools.auto', 'schools.history', 'count.draw'):
            self.play(g, cid)
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual([r.origin for r in f.rows], ['hand', 'effect', 'history', 'draw'])
        self.assertEqual((f.quantity, f.after), (1, 4))
        self.assertEqual([r.spell_school for r in f.rows], [SpellSchool.FIRE, SpellSchool.FROST, SpellSchool.FIRE, SpellSchool.SHADOW])
        self.portable(g)

    def test_repeat_row_does_not_add_a_new_school_to_a_personal_root(self):
        g = self.two_fire()
        f = self.fact(g).intrinsic.player_spells
        other = replace(f.rows[-1], origin='repeat', iteration=2, spell_school=SpellSchool.HOLY)
        changed = replace(f, rows=(f.rows[0], other))
        self.assertEqual((changed.quantity, changed.after), (1, 4))
        self.assertFalse(other.counts_for(1))

    def test_accepted_waiting_personal_payload_counts_before_completion(self):
        g = self.game(hand=(WISDOM, 'schools.wait'))
        self.play(g, 'schools.wait')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(cast_spells(g.state, 1, successful=True)), 0)
        self.assertEqual((self.fact(g).intrinsic.player_spells.quantity, self.price(g)), (1, 4))
        restored = self.portable(g)
        for current in (g, restored):
            self.choose(current)
        self.assertEqual(restored.snapshot(), g.snapshot())

    def test_unaccepted_automatic_wait_keeps_frozen_prefix_and_original_price(self):
        g = self.game(hand=(WISDOM, 'schools.auto'), board=('count.auto.watch',))
        self.play(g, 'schools.auto')
        stage = self.fact(g).intrinsic
        self.assertFalse(stage.player_spells.rows[0].payload_started)
        self.assertEqual(stage.amount, 5)
        restored = self.portable(g)
        for current in (g, restored):
            self.choose(current)
        self.assertEqual(restored.snapshot(), g.snapshot())
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        self.assertEqual(self.price(g), 5)

    def test_schools_cast_before_card_acquisition_are_available(self):
        g = self.game(hand=('schools.fire', 'schools.frost', 'schools.acquire'))
        for cid in ('schools.fire', 'schools.frost', 'schools.acquire'):
            self.play(g, cid)
        self.assertEqual(self.price(g), 3)
        self.assertEqual([(a.kind, a.origin, a.behavior_id) for a in self.source(g).abilities],
                         [('on_play', 'printed', 'schools.wisdom')])
        self.portable(g)

    def test_repeated_same_school_does_not_become_a_cost_counter(self):
        g = self.game(hand=(WISDOM, old.ARCANE, 'schools.refill'))
        for _ in range(12):
            self.play(g, 'schools.refill')
        self.assertEqual((self.price(g), self.price(g, old.ARCANE)), (4, 0))
        self.assertEqual(self.fact(g).intrinsic.player_spells.quantity, 1)
        self.portable(g)

    def test_physical_and_generated_quotes_are_pure_and_share_same_original_set(self):
        g = self.two_fire(extras=('schools.frost',))
        self.play(g, 'schools.frost')
        before = g.snapshot()
        for _ in range(3):
            generated = capture_generated_quote_fact(g.state, g.registry, 1, WISDOM)
            self.assertEqual((generated.amount, generated.intrinsic.player_spells),
                (self.price(g), self.fact(g).intrinsic.player_spells))
            self.assertEqual(quote_generated_cost(g.state, g.registry, 1, WISDOM).amount, 3)
            g.legal_actions()
        self.assertEqual(g.snapshot(), before)

    def test_native_does_not_discount_its_original_payment_by_its_own_arcane_cast(self):
        g = self.two_fire(mana=4)
        source = self.play(g, WISDOM)
        root = g.state.play_history[-1]
        self.assertEqual((root.source_id, root.cost, root.submitted_cost.quote.intrinsic.player_spells.quantity), (source, 4, 1))
        self.assertEqual(g.state.players[1].mana, 0)
        # The accepted native now adds Arcane for future prices.
        self.assertEqual(quote_generated_cost(g.state, g.registry, 1, WISDOM).amount, 3)
        self.portable(g)

    def test_insufficient_mana_rejects_without_changes_to_histories_or_rng(self):
        g = self.two_fire(mana=3)
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, WISDOM)
        self.assertEqual(g.snapshot(), saved)

    def test_committed_wait_restores_original_set_and_does_not_repay(self):
        self.options = {'committed_wait': True}
        g = self.two_fire(board=('schools.watch.card_committed',), mana=4)
        source = self.play(g, WISDOM)
        self.assertIsNotNone(g.state.pending_choice)
        root = g.state.play_history[-1]
        self.assertEqual((root.cost, root.submitted_cost.quote.intrinsic.player_spells.quantity, g.state.players[1].mana), (4, 1, 0))
        restored = self.portable(g)
        for current in (g, restored):
            self.choose(current)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual((g.state.play_history[-1].source_id, g.state.play_history[-1].submitted_cost), (source, root.submitted_cost))
        self.assertEqual(g.state.players[1].mana, 0)
        self.portable(g)

    def test_payload_draw_wait_restores_original_school_enum_and_price(self):
        self.options = {'payload_wait': True}
        g = self.two_fire(board=('schools.watch.card_drawn',))
        self.play(g, WISDOM)
        self.assertIsNotNone(g.state.pending_choice)
        receipt = g.state.play_history[-1].submitted_cost
        restored = self.portable(g)
        row = restored.state.play_history[-1].submitted_cost.quote.intrinsic.player_spells.rows[0]
        self.assertIs(type(row.spell_school), SpellSchool)
        for current in (g, restored):
            self.choose(current)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual((g.state.play_history[-1].submitted_cost, len(g.state.draw_history)), (receipt, 2))
        self.portable(g)

    def test_failed_choice_restores_payment_histories_deck_and_private_view(self):
        self.options = {'payload_wait': True}
        g = self.two_fire(board=('schools.watch.card_drawn',))
        self.play(g, WISDOM)
        saved, view = g.snapshot(), g.observe(1)
        with self.assertRaisesRegex(ResolutionError, 'missing.school.fixture'):
            self.choose(g, 'fault')
        self.assertEqual((g.snapshot(), g.observe(1)), (saved, view))
        self.portable(g)

    def test_rows_reject_untyped_schools_and_bind_valid_school_to_original_face(self):
        g = self.two_fire()
        stage = self.fact(g).intrinsic
        f = stage.player_spells
        for value in ('fire', True, 2):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(f.rows[0], spell_school=value)
        changed = replace(f, rows=tuple(replace(row, spell_school=SpellSchool.HOLY) for row in f.rows))
        bad = replace(stage, player_spells=changed)
        with self.assertRaisesRegex(ValueError, 'original declared school'):
            validate_intrinsic_stage_fact(g.registry, bad)
        with self.assertRaises(ValueError):
            validate_intrinsic_history_prefix(bad, g.state, g.registry)

    def test_complete_rows_cannot_be_reordered_trimmed_or_have_wrong_distinct_quantity(self):
        g = self.two_fire()
        f = self.fact(g).intrinsic.player_spells
        for changes in ({'rows': f.rows[:1]}, {'rows': f.rows[::-1]}, {'quantity': 2, 'after': 3},
                        {'rows': list(f.rows)}, {'quantity': True}, {'cast_history_length': 3}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(f, **changes)

    def test_unknown_excluded_original_faces_are_not_hidden_by_zero_school_count(self):
        g = self.game(hand=(WISDOM, 'schools.auto'))
        self.play(g, 'schools.auto')
        state = g.state
        state.cast_history[0] = replace(state.cast_history[0], card_id='missing.school.original')
        with self.assertRaisesRegex(ValueError, 'missing.school.original'):
            capture_quote_fact(state, g.registry, capture_cost_input(state.entities[self.source(g).id]))

    def test_saved_original_school_is_required_typed_and_not_rewritable(self):
        g = self.two_fire()
        self.play(g, WISDOM)
        saved = g.snapshot()
        for edit in ('missing', 'extra', 'unknown', 'boolean', 'other_school', 'other_profile'):
            bad = deepcopy(saved)
            personal = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['player_spells']
            row = personal['rows'][0]
            if edit == 'missing': del row['spell_school']
            elif edit == 'extra': row['invented_school'] = 'fire'
            elif edit == 'unknown': row['spell_school'] = 'unknown'
            elif edit == 'boolean': row['spell_school'] = True
            elif edit == 'other_school': row['spell_school'] = 'holy'
            else: personal['spec']['profile_id'] = 'cost.player-spell-count-v1'
            with self.subTest(edit=edit), self.assertRaises(SnapshotError):
                Game.from_snapshot(old.rehash(bad), registry())

    def test_player_price_shows_amount_without_private_history_or_school_set(self):
        g = self.two_fire(enemy_hand=(WISDOM, 'schools.frost'))
        view = g.observe(1)
        self.assertEqual(view['players'][0]['hand'][0]['cost']['amount'], 4)
        self.assertTrue(all(row['card_id'] is None and row.get('cost') is None for row in view['players'][1]['hand']))
        for key in ('player_spells', 'cast_history', 'spell_school', 'submitted_cost', 'cast_history_length', 'next_entity_id'):
            self.assertNotIn(key, json.dumps(view))
        self.portable(g)

    def test_new_strict_row_layout_rejects_all_old_future_boolean_and_host_versions(self):
        g = self.game()
        saved = g.snapshot()
        self.assertEqual((saved['schema_version'], g.ruleset.id, g.mechanics.version), (SNAPSHOT_SCHEMA_VERSION, 'prototype-v302', CORE_EFFECTS_VERSION))
        self.assertEqual((g.observe(1)['version'], g.for_player(1).observe()['version']), ('player-view-v86', 'player-actions-v12'))
        self.assertEqual(build_replay(g)['schema_version'], 1)
        for version in (*range(1, 218), 217, True, 208.0):
            bad = deepcopy(saved)
            bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(SnapshotError, f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
                Game.from_snapshot(bad, registry())
        for field, value in (('ruleset', 'prototype-v223'), ('mechanics_version', 'core-effects-v217')):
            bad = deepcopy(saved)
            if field == 'ruleset':
                bad[field]['id'] = value
            else:
                bad[field]['version'] = value
            with self.subTest(field=field), self.assertRaises(SnapshotError):
                Game.from_snapshot(old.rehash(bad), registry())

    def test_waiting_typed_frames_reject_missing_or_untyped_school_operands(self):
        self.options = {'committed_wait': True}
        g = self.two_fire(board=('schools.watch.card_committed',))
        self.play(g, WISDOM)
        saved = g.snapshot()

        def rows(value):
            if isinstance(value, dict):
                if value.get('type') == 'hs_sim.engine.model.PlayerSpellCountCostRow':
                    yield value['fields']
                for nested in value.values():
                    yield from rows(nested)
            elif isinstance(value, list):
                for nested in value:
                    yield from rows(nested)

        self.assertTrue(list(rows(saved['resolution_frame'])))
        for edit in ('missing', 'untyped', 'other_school'):
            bad = deepcopy(saved)
            originals = list(rows(bad['resolution_frame']))
            for row in originals:
                if edit == 'missing': del row['spell_school']
                elif edit == 'untyped': row['spell_school'] = 'fire'
                else: row['spell_school']['value'] = 'holy'
            with self.subTest(edit=edit), self.assertRaises(SnapshotError):
                Game.from_snapshot(old.rehash(bad), registry(**self.options))


if __name__ == '__main__':
    unittest.main()
