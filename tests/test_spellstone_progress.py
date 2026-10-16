"""Jasper's own weighted progress and upgrade cost policy on the common engine."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, Game, HandProgressSpec,
    PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError,
    SpellSchool, TargetSpec, Zone)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage, GainArmor,
    ModifyCost, RequestChoice)
from hs_sim.engine.hand_progress import AdvanceHandProgress, advance_value, identity, progress_ability
from hs_sim.engine.model import AbilityInstance, DamageKind, Event
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry


BASE, MID, MAXIMUM = 'LOOT_051', 'LOOT_051t1', 'LOOT_051t2'
PIN = 'd749657a676431f765473d959b64a7131fd67ae8394489e41ebeed23b94e22c8'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/spellstone-progress.json'


def evidence():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Complete Jasper raw evidence changed')
    for row in data['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete original Jasper record changed')
    return {row['id']: row['data'] for row in data['records']}


def registry(scripts=(), *, choice_probe=False, bad_condition=False, fail_progress=False):
    r = opening_registry()
    condition = 'jasper.owner.armor'
    r.register_trigger_condition(condition, (lambda c: 'invalid') if bad_condition else
        lambda c: c.event.player_id == c.player_id)
    rows = evidence()
    for cid, amount, following in ((MAXIMUM, 6, None), (MID, 4, MAXIMUM), (BASE, 2, MID)):
        row = rows[cid]
        r.register_behavior('jasper.' + cid, lambda c, n=amount:
            (Damage(c.target_id, n, c.source_id, DamageKind.SPELL),))
        spec = (HandProgressSpec('event', 3, following, event='armor_gained',
            condition_id=condition, amount_basis='event_amount', upgrade_cost_policy='clear_local')
            if following else None)
        r.register_card(CardDefinition(cid, row['name'], CardType.SPELL, cost=row['cost'],
            on_play='jasper.' + cid, targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)),
            hand_progress=spec, spell_school=SpellSchool.NATURE,
            metadata=metadata(CardClass.DRUID, rarity=Rarity.RARE, collectible=cid == BASE)))
    r.register_card(CardDefinition('probe.unit', 'Unit', CardType.MINION,
        attack=1, health=12, metadata=metadata()))
    if choice_probe or fail_progress:
        def completion(c):
            if fail_progress:
                raise ResolutionError('Deliberate progress rollback probe')
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'OK', (GainArmor(c.player_id, 1),)),),
                source_id=c.source_id),)
        r.register_behavior('probe.complete', completion)
        r.register_behavior('probe.noop', lambda c: ())
        r.register_card(CardDefinition('probe.counter', 'Weighted counter probe', CardType.SPELL,
            on_play='probe.noop', hand_progress=HandProgressSpec('event', 3,
                on_complete='probe.complete', event='armor_gained', condition_id=condition,
                amount_basis='event_amount'), metadata=metadata()))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    return r


class SpellstoneProgressTests(unittest.TestCase):
    def setUp(self):
        self.scripts = []
        self.options = {}

    def script(self, name, callback):
        self.scripts.append((name, callback))

    def armor(self, name, amount, player=1):
        self.script(name, lambda c: (GainArmor(player, amount),))

    def game(self, hand=(BASE,), deck=(), enemy_hand=(), enemy_board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, deck=deck, max_mana=10, mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, max_mana=10, mana=10)), seed=61),
            registry(self.scripts, **self.options))

    def play(self, g, card, target=None):
        player = g.state.active_player
        source = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == card)
        g.apply(PlayCard(player, source, target)); return source

    def entity(self, g, card=BASE, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if g.state.entities[i].card_id == card)

    def ref(self, c, card=BASE, zone=Zone.HAND, player=1):
        return CardReference.capture(next(c.state.entities[i]
            for i in getattr(c.state.players[player], zone.value) if c.state.entities[i].card_id == card))

    def progress(self, g, card=BASE, player=1):
        return progress_ability(self.entity(g, card, player))

    def choose(self, g):
        pending = g.state.pending_choice
        g.apply(SelectChoice(pending.player_id, pending.id, (pending.options[0].id,)))

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored

    def test_full_real_three_form_evidence_and_body_values(self):
        rows = evidence(); r = registry()
        self.assertEqual(set(rows), {BASE, MID, MAXIMUM})
        for cid in (BASE, MID, MAXIMUM):
            d = r.card(cid)
            self.assertEqual((d.name, d.cost, d.kind), (rows[cid]['name'], 1, CardType.SPELL))
            self.assertEqual(d.spell_school, SpellSchool.NATURE)
        self.assertEqual(r.card(BASE).hand_progress.amount_basis, 'event_amount')
        self.assertEqual(r.card(MID).hand_progress.upgrade_cost_policy, 'clear_local')
        self.assertIsNone(r.card(MAXIMUM).hand_progress)

    def test_two_armor_is_two_units_from_one_witness(self):
        self.armor('armor', 2); g = self.game(hand=('armor', BASE)); self.play(g, 'armor')
        a = self.progress(g)
        self.assertEqual((a.progress_value, a.progress_completions, a.progress_units), (2, 0, (2,)))
        self.assertEqual(len(a.progress_keys), 1); self.portable(g)

    def test_separate_armor_events_accumulate_to_one_upgrade(self):
        self.armor('one', 1); self.armor('two', 2)
        g = self.game(hand=('one', 'two', BASE)); target = self.entity(g).id
        self.play(g, 'one'); self.play(g, 'two'); a = self.progress(g, MID)
        self.assertEqual((self.entity(g, MID).id, a.progress_value, a.progress_completions), (target, 0, 1))
        self.assertEqual(a.progress_units, (1, 2)); self.portable(g)

    def test_oversized_event_upgrades_once_without_carrying_excess(self):
        self.armor('large', 8); self.armor('one', 1)
        g = self.game(hand=('large', 'one', BASE)); self.play(g, 'large')
        a = self.progress(g, MID)
        self.assertEqual((a.progress_value, a.progress_completions, a.progress_units), (0, 1, (3,)))
        self.play(g, 'one'); self.assertEqual(self.progress(g, MID).progress_value, 1)
        self.portable(g)

    def test_overshoot_with_partial_progress_does_not_feed_next_stage(self):
        self.armor('two', 2); self.armor('large', 8)
        g = self.game(hand=('two', 'large', BASE)); self.play(g, 'two'); self.play(g, 'large')
        a = self.progress(g, MID)
        self.assertEqual((a.progress_value, a.progress_completions, a.progress_units), (0, 1, (2, 1)))

    def test_two_actual_events_complete_both_stages(self):
        self.script('armor', lambda c: (GainArmor(1, 6), GainArmor(1, 6)))
        g = self.game(hand=('armor', BASE)); original = self.entity(g).id; self.play(g, 'armor')
        a = self.progress(g, MAXIMUM)
        self.assertEqual((self.entity(g, MAXIMUM).id, a.progress_value, a.progress_completions), (original, 3, 2))
        self.assertEqual(a.progress_units, (3, 3)); self.assertTrue(a.consumed); self.portable(g)

    def test_final_stage_does_not_restart_after_more_armor(self):
        self.script('armor', lambda c: (GainArmor(1, 3), GainArmor(1, 3), GainArmor(1, 3)))
        g = self.game(hand=('armor', BASE)); self.play(g, 'armor')
        self.assertEqual(self.progress(g, MAXIMUM).progress_units, (3, 3))
        self.assertEqual(sum(e.kind == 'hand_card_upgraded' for e in g.events), 2)

    def test_same_name_physical_cards_each_keep_own_progress(self):
        self.armor('armor', 2); g = self.game(hand=('armor', BASE, BASE)); self.play(g, 'armor')
        cards = [g.state.entities[i] for i in g.state.players[1].hand]
        rows = [progress_ability(e) for e in cards]
        self.assertEqual([a.progress_value for a in rows], [2, 2])
        self.assertEqual(len({a.id for a in rows}), 2); self.portable(g)

    def test_only_controller_armor_counts(self):
        self.armor('armor', 2, player=2)
        g = self.game(hand=('armor', BASE), enemy_hand=(BASE,)); self.play(g, 'armor')
        self.assertEqual(self.progress(g).progress_value, 0)
        self.assertEqual(self.progress(g, player=2).progress_units, (2,))

    def test_zero_event_does_not_add_witness_or_progress(self):
        self.armor('armor', 0); g = self.game(hand=('armor', BASE)); self.play(g, 'armor')
        a = self.progress(g); self.assertEqual((a.progress_value, a.progress_units, a.progress_keys), (0, (), ()))

    def test_deck_card_does_not_listen_or_retroactively_count(self):
        self.armor('armor', 8)
        self.script('take', lambda c: (MoveCard(self.ref(c, zone=Zone.DECK), 1, Zone.HAND),))
        g = self.game(hand=('armor', 'take'), deck=(BASE,)); self.play(g, 'armor'); self.play(g, 'take')
        self.assertEqual((self.progress(g).progress_value, self.progress(g).progress_units), (0, ()))

    def test_obtained_before_later_armor_in_same_action_counts(self):
        self.script('acquire', lambda c: (AddToHand(1, BASE), GainArmor(1, 3)))
        g = self.game(hand=('acquire',)); self.play(g, 'acquire')
        self.assertEqual(self.progress(g, MID).progress_units, (3,)); self.portable(g)

    def test_current_copy_inherits_units_base_copy_starts_empty(self):
        self.armor('two', 2)
        self.script('copy', lambda c: (CopyCard(self.ref(c), 1, mode='current'),
            CopyCard(self.ref(c), 1, mode='base')))
        self.armor('one', 1)
        g = self.game(hand=('two', 'copy', 'one', BASE)); self.play(g, 'two'); self.play(g, 'copy')
        self.assertEqual([progress_ability(g.state.entities[i]).progress_value for i in g.state.players[1].hand
            if g.state.entities[i].card_id == BASE], [2, 2, 0])
        self.play(g, 'one')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [MID, MID, BASE])
        self.portable(g)

    def test_normal_move_preserves_earned_units_but_deck_does_not_grow(self):
        self.armor('two', 2)
        self.script('store', lambda c: (MoveCard(self.ref(c), 1, Zone.DECK), GainArmor(1, 8)))
        self.script('take', lambda c: (MoveCard(self.ref(c, zone=Zone.DECK), 1, Zone.HAND), GainArmor(1, 1)))
        g = self.game(hand=('two', 'store', 'take', BASE)); self.play(g, 'two'); self.play(g, 'store')
        a = progress_ability(self.entity(g, zone=Zone.DECK)); self.assertEqual(a.progress_units, (2,))
        self.play(g, 'take'); self.assertEqual(self.progress(g, MID).progress_units, (2, 1)); self.portable(g)

    def test_partial_progress_keeps_local_cost_until_actual_upgrade(self):
        self.script('discount', lambda c: (ModifyCost(self.ref(c).entity_id, CostSpec(delta=-1)), GainArmor(1, 2)))
        self.armor('one', 1)
        g = self.game(hand=('discount', 'one', BASE)); self.play(g, 'discount')
        self.assertEqual(self.entity(g).cost, 0); self.play(g, 'one')
        self.assertEqual(self.entity(g, MID).cost, 1)
        self.assertFalse(self.entity(g, MID).enchantments); self.portable(g)

    def test_upgrade_clears_local_set_cost_and_keeps_player_modifier(self):
        self.script('discount', lambda c: (AddCostModifier(1, CostSpec(delta=-1, card_ids=(BASE, MID, MAXIMUM))),
            ModifyCost(self.ref(c).entity_id, CostSpec(set_to=6)), GainArmor(1, 3)))
        g = self.game(hand=('discount', BASE)); self.play(g, 'discount')
        self.assertEqual(g.quote_cost(self.entity(g, MID).id).amount, 0)
        self.assertEqual(len(g.state.players[1].cost_modifiers), 1); self.portable(g)

    def test_upgraded_body_uses_four_damage_and_normal_spell_payment(self):
        self.armor('armor', 3); g = self.game(hand=('armor', BASE), enemy_board=('probe.unit',))
        self.play(g, 'armor'); target = g.state.players[2].board[0]; source = self.play(g, MID, target)
        self.assertEqual(g.state.entities[target].health, 8)
        self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual(g.state.play_history[-1].source_id, source); self.portable(g)

    def test_printed_maximum_body_uses_six_damage_without_growth_state(self):
        g = self.game(hand=(MAXIMUM,), enemy_board=('probe.unit',)); target = g.state.players[2].board[0]
        self.play(g, MAXIMUM, target); self.assertEqual(g.state.entities[target].health, 6)
        self.portable(g)

    def test_duplicate_witness_cannot_advance_again_after_upgrade(self):
        def callback(c):
            e = c.state.entities[self.ref(c).entity_id]
            event = Event(999, c.state.action_number, 'armor_gained', player_id=1, amount=6)
            effect = AdvanceHandProgress(identity(e, progress_ability(e)), event)
            return (effect, effect)
        self.script('witness', callback); g = self.game(hand=('witness', BASE)); self.play(g, 'witness')
        self.assertEqual((self.progress(g, MID).progress_value, self.progress(g, MID).progress_units), (0, (3,)))

    def test_huge_event_has_single_bounded_witness(self):
        self.armor('armor', 1000000); g = self.game(hand=('armor', BASE)); self.play(g, 'armor')
        a = self.progress(g, MID); self.assertEqual(a.progress_units, (3,)); self.assertEqual(len(a.progress_keys), 1)

    def test_weighted_completion_wait_restores_without_recount(self):
        self.options['choice_probe'] = True; self.armor('armor', 8)
        g = self.game(hand=('armor', 'probe.counter')); self.play(g, 'armor')
        a = self.progress(g, 'probe.counter'); self.assertEqual((a.progress_value, a.progress_units), (3, (3,)))
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_waiting_batch_keeps_next_captured_weighted_event(self):
        self.options['choice_probe'] = True; self.armor('armor', 3)
        g = self.game(hand=('armor', 'probe.counter', 'probe.counter')); self.play(g, 'armor')
        restored = self.portable(g)
        while g.state.pending_choice:
            self.choose(g); self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.portable(g)
        values = [progress_ability(g.state.entities[i]).progress_units for i in g.state.players[1].hand]
        # Resolving the first completion emits a new one-armor event before
        # the next card consumes its captured three-armor event. Both count;
        # the older event accepts only the two units still needed.
        self.assertEqual(values, [(3,), (1, 2)])

    def test_hidden_progress_exposes_no_units_or_witness_identity(self):
        self.armor('armor', 2); g = self.game(hand=('armor', BASE)); self.play(g, 'armor')
        own = g.observe(1)['players'][0]['hand'][0]
        self.assertEqual(own['hand_progress']['value'], 2)
        enemy = g.observe(2)['players'][0]['hand'][0]
        self.assertNotIn('hand_progress', enemy)
        for row in (own, enemy):
            self.assertNotIn('progress_units', row); self.assertNotIn('progress_keys', row)
        self.assertFalse(any(e['kind'] in ('hand_progressed', 'hand_card_upgraded') for e in g.player_events(2)))

    def test_bad_condition_rolls_back_rng_payment_armor_and_progress(self):
        self.options['bad_condition'] = True
        self.script('armor', lambda c: (AddToDeck(1, 'card.1'), GainArmor(1, 3)))
        g = self.game(hand=('armor', BASE)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'armor')
        self.assertEqual(g.snapshot(), before)

    def test_completion_exception_rolls_back_all_weighted_state(self):
        self.options['fail_progress'] = True; self.armor('armor', 3)
        g = self.game(hand=('armor', 'probe.counter')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'armor')
        self.assertEqual(g.snapshot(), before)

    def test_noninteger_event_amount_is_explicit_error(self):
        def callback(c):
            e = c.state.entities[self.ref(c).entity_id]
            return (AdvanceHandProgress(identity(e, progress_ability(e)),
                Event(999, c.state.action_number, 'armor_gained', player_id=1, amount=True)),)
        self.script('bad', callback); g = self.game(hand=('bad', BASE)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_invalid_public_amount_and_cost_policies_rejected(self):
        common = dict(kind='event', goal=3, upgrade_card_id=MID, event='armor_gained')
        for changes in (dict(amount_basis='guess'), dict(amount_basis=True),
                dict(amount_basis='event_amount', repeat=True, upgrade_card_id=None, on_complete='noop'),
                dict(kind='infuse', event=None, amount_basis='event_amount'),
                dict(upgrade_cost_policy='guess'), dict(upgrade_cost_policy=False),
                dict(upgrade_cost_policy='clear_local', upgrade_card_id=None, on_complete='noop')):
            with self.subTest(changes=changes), self.assertRaises(ValueError): HandProgressSpec(**(common | changes))

    def test_unit_mode_preserves_existing_one_per_witness_contract(self):
        spec = HandProgressSpec('event', 3, on_complete='noop', event='armor_gained')
        a = AbilityInstance(1, kind='hand_progress', hand_progress=spec)
        a = advance_value(a, 'event:1'); a.__post_init__()
        self.assertEqual((a.progress_value, a.progress_units), (1, (1,)))
        with self.assertRaises(ValueError): advance_value(a, 'event:2', 2)
        # Imported unit-mode state cannot inflate the old one-per-event rule
        # by supplying a positive but fabricated multi-unit receipt.
        with self.assertRaises(ValueError): replace(a, progress_value=2, progress_units=(2,))

    def test_snapshot_requires_matching_positive_unit_receipts(self):
        self.armor('armor', 2); g = self.game(hand=('armor', BASE)); self.play(g, 'armor')
        eid = self.entity(g).id
        for kind in ('missing', 'empty', 'bool', 'zero', 'insufficient', 'mutable'):
            bad = g.snapshot()
            a = next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind'] == 'hand_progress')
            if kind == 'missing': del a['progress_units']
            elif kind == 'empty': a['progress_units'] = []
            elif kind == 'bool': a['progress_units'] = [True]
            elif kind == 'zero': a['progress_units'] = [0]
            elif kind == 'insufficient': a['progress_units'] = [1]
            else: a['progress_units'] = {}
            with self.subTest(kind=kind), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry(self.scripts))

    def test_new_schema_rejects_old_future_or_bool(self):
        g = self.game(); self.assertEqual(g.snapshot()['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        for version in (1, 158, 159, 160, 161, 162, 217, True):
            bad = g.snapshot(); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())
