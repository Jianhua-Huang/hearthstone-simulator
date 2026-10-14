"""Necessary public-action evidence for the isolated pure/Spell H2 slice."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

import test_m5_owner_turn_history as fixtures
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IntrinsicCostSpec,
    Keyword, PlayCard, ResolutionError, SelectChoice, SnapshotError, SpellSchool)
from hs_sim.engine.costs import (capture_cost_input, capture_quote_fact,
    capture_generated_quote_fact, quote_cost, quote_generated_cost)
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, GainArmor,
    ModifyCost, RequestChoice, Transform)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_history_prefix, validate_intrinsic_origin,
    validate_intrinsic_stage_fact)
from hs_sim.engine.model import (CostSpec, PaymentType, Resource, RepeatCostFilter,
    RepeatMatchSpec, SpellRepeatSpec, TargetSpec, Zone)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class IntrinsicStageTests(unittest.TestCase):
    game = fixtures.OwnerTurnActionTests.game
    play = fixtures.OwnerTurnActionTests.play
    end = fixtures.OwnerTurnActionTests.end
    choose = fixtures.OwnerTurnActionTests.choose

    def setUp(self):
        self.r = fixtures.registry()
        self.r.register_card(CardDefinition('intrinsic-minion', 'intrinsic-minion', CardType.MINION,
            cost=5, attack=1, health=5, metadata=fixtures.metadata(('dragon',)),
            intrinsic_costs=(IntrinsicCostSpec(delta=-3),)))
        self.r.register_card(CardDefinition('intrinsic-spell', 'intrinsic-spell', CardType.SPELL,
            cost=5, on_play='nothing', spell_school=SpellSchool.ARCANE,
            metadata=fixtures.metadata(), intrinsic_costs=(IntrinsicCostSpec(delta=-3),)))

    def source(self, g, card, player=1):
        return next(g.state.entities[i] for i in g.state.players[player].hand
                    if g.state.entities[i].card_id == card)

    def fact(self, g, card, player=1):
        return capture_quote_fact(g.state, self.r, capture_cost_input(self.source(g, card, player)))

    def closed_arcane(self, *hand, enemy_hand=()):
        g = self.game(('arcane', *hand), enemy_hand)
        self.play(g, 'arcane'); self.end(g); self.end(g)
        return g

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, self.r).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), saved)
        return saved

    def reject(self, saved):
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, self.r)

    def test_empty_stage_and_first_turn_are_explicit(self):
        g = self.game(('arcane', 'intrinsic-spell', 'intrinsic-minion'))
        empty = self.fact(g, 'arcane')
        self.assertEqual((empty.intrinsic.rules, empty.intrinsic.condition_facts, empty.intrinsic.amount), ((), (), 0))
        self.play(g, 'arcane')
        for card in ('intrinsic-spell', 'intrinsic-minion'):
            fact = self.fact(g, card)
            self.assertEqual(fact.amount, 5)
            condition, = fact.intrinsic.condition_facts
            self.assertIsNone(condition.owner_turn)
            self.assertFalse(condition.matched)
            validate_intrinsic_origin(fact.intrinsic, g.state, self.r)

    def test_complete_minion_relation_contains_false_and_true_rows(self):
        g = self.game(('beast', 'dragon', 'empty', 'intrinsic-minion'))
        for card in ('beast', 'dragon', 'empty'): self.play(g, card)
        self.end(g); self.end(g)
        fact = self.fact(g, 'intrinsic-minion')
        self.assertEqual(fact.amount, 2)
        self.assertEqual(tuple(row.matched for row in fact.intrinsic.condition_facts[0].rows), (False, True, False))
        self.assertEqual(fact.intrinsic.boundary.play_history_length, 3)
        validate_intrinsic_stage_fact(self.r, fact.intrinsic)
        validate_intrinsic_history_prefix(fact.intrinsic, g.state, self.r)

    def test_nonactive_player_uses_own_recent_closed_interval(self):
        g = self.game(('dragon', 'intrinsic-minion'), ('beast', 'intrinsic-minion'))
        self.play(g, 'dragon'); self.end(g); self.play(g, 'beast'); self.end(g)
        self.assertEqual((self.fact(g, 'intrinsic-minion').amount,
                          self.fact(g, 'intrinsic-minion', 2).amount), (2, 5))
        self.assertEqual(self.fact(g, 'intrinsic-minion', 2).intrinsic.condition_facts[0].owner_turn.turn, 2)

    def test_unknown_later_history_is_not_hidden_by_true_or_zero(self):
        g = self.game(('dragon', 'unknown', 'intrinsic-minion'))
        self.play(g, 'dragon'); self.play(g, 'unknown'); self.end(g); self.end(g)
        before = g.snapshot()
        with self.assertRaisesRegex(ValueError, 'known Minion tribes'): self.fact(g, 'intrinsic-minion')
        self.assertEqual(g.snapshot(), before)

    def test_unknown_subject_errors_without_any_old_interval(self):
        definition = replace(self.r.card('intrinsic-minion'), id='unknown-intrinsic', name='unknown-intrinsic',
                             metadata=fixtures.metadata(None))
        self.r.register_card(definition)
        g = self.game(('unknown-intrinsic',))
        with self.assertRaisesRegex(ValueError, 'unknown Minion tribes'): self.fact(g, 'unknown-intrinsic')
        before = g.snapshot()
        with self.assertRaisesRegex(ValueError, 'unknown Minion tribes'): self.play(g, 'unknown-intrinsic')
        self.assertEqual(g.snapshot(), before)

    def test_all_relation_is_symmetric_and_known_empty_is_false(self):
        for card, tribe in (('all-subject', ('all',)), ('empty-subject', ())):
            self.r.register_card(replace(self.r.card('intrinsic-minion'), id=card, name=card,
                                         metadata=fixtures.metadata(tribe)))
        g = self.game(('all', 'intrinsic-minion'))
        self.play(g, 'all'); self.end(g); self.end(g)
        self.assertEqual(self.fact(g, 'intrinsic-minion').amount, 2)
        g2 = self.game(('dragon', 'all-subject', 'empty-subject'))
        self.play(g2, 'dragon'); self.end(g2); self.end(g2)
        self.assertEqual((self.fact(g2, 'all-subject').amount, self.fact(g2, 'empty-subject').amount), (2, 5))

    def test_ordered_intrinsic_then_local_and_external_and_final_floor(self):
        self.r.register_card(replace(self.r.card('intrinsic-spell'), id='ordered', name='ordered',
            intrinsic_costs=(IntrinsicCostSpec(delta=-3), IntrinsicCostSpec(set_to=4), IntrinsicCostSpec(delta=-2, minimum=1))))
        self.r.register_behavior('layers', lambda c: [ModifyCost(c.target_id, CostSpec(set_to=6)),
            AddCostModifier(c.player_id, CostSpec(delta=-4), uses_remaining=1)])
        self.r.register_card(CardDefinition('layers', 'layers', CardType.SPELL, on_play='layers',
            targeting=TargetSpec(zones=(Zone.HAND,), kinds=(CardType.SPELL,)), metadata=fixtures.metadata()))
        g = self.closed_arcane('ordered', 'layers')
        subject = self.source(g, 'ordered')
        self.play(g, 'layers', target=subject.id)
        fact = self.fact(g, 'ordered')
        self.assertEqual(tuple((o.before, o.after) for o in fact.intrinsic.operations), ((5,2),(2,4),(4,2)))
        self.assertEqual((fact.intrinsic.amount, fact.local_amount, fact.amount), (2, 6, 2))
        self.assertEqual(len(fact.consumable_ids), 1)
        from hs_sim.engine.repeat_matching import validate_cost_quote_fact
        validate_cost_quote_fact(self.r, fact)
        self.assertEqual(quote_cost(g.state, self.r, self.source(g, 'ordered')).amount, 2)

    def test_generated_initial_cost_after_same_intrinsic_and_pure_state(self):
        g = self.closed_arcane('intrinsic-spell')
        before = g.snapshot()
        fact = capture_generated_quote_fact(g.state, self.r, 1, 'intrinsic-spell',
            cost=CostSpec(set_to=4), minimum_cost=6)
        self.assertEqual((fact.intrinsic.amount, fact.local_amount, fact.amount), (2, 4, 6))
        self.assertFalse(hasattr(fact.quote_input, 'source_id'))
        validate_generated_quote_fact(self.r, fact)
        self.assertEqual(quote_generated_cost(g.state, self.r, 1, 'intrinsic-spell').amount, 2)
        self.assertEqual(g.snapshot(), before)

    def test_entity_raw_cache_does_not_materialize_intrinsic(self):
        g = self.closed_arcane('intrinsic-spell')
        source = self.source(g, 'intrinsic-spell')
        before = deepcopy(g.state)
        self.assertEqual((source.cost, source.base_cost, source.cost_modifier), (5, 5, 0))
        self.assertEqual(quote_cost(g.state, self.r, source).amount, 2)
        self.assertEqual(g.state, before)

    def test_physical_base_differs_from_printed_and_is_preserved(self):
        g = self.closed_arcane('intrinsic-spell')
        state = g.state
        source = self.source(g, 'intrinsic-spell')
        value = replace(capture_cost_input(source), base_cost=9)
        fact = capture_quote_fact(state, self.r, value)
        self.assertEqual((fact.intrinsic.printed_cost, fact.intrinsic.base_cost, fact.amount), (5, 9, 6))
        from hs_sim.engine.repeat_matching import validate_cost_quote_fact
        validate_cost_quote_fact(self.r, fact)

    def test_actual_paid_spell_receipt_and_history_prefix_survive_later_turns(self):
        g = self.closed_arcane('intrinsic-spell')
        mana = g.state.players[1].mana
        self.play(g, 'intrinsic-spell')
        play = g.state.play_history[-1]
        self.assertEqual((play.cost, g.state.players[1].mana), (2, mana-2))
        self.assertEqual(play.submitted_cost.quote.intrinsic.boundary.play_history_length, 1)
        self.portable(g)
        self.end(g); self.end(g)
        self.portable(g)

    def test_spell_waiting_restore_and_complete_original_stage(self):
        self.r.register_card(replace(self.r.card('intrinsic-spell'), id='intrinsic-choice', name='intrinsic-choice', on_play='choice'))
        g = self.closed_arcane('intrinsic-choice')
        self.play(g, 'intrinsic-choice')
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g)
        self.choose(g)
        self.portable(g)
        self.assertEqual(g.state.play_history[-1].submitted_cost.quote.intrinsic.amount, 2)

    def test_local_only_spell_matching_has_required_intrinsic_stage(self):
        spec = SpellRepeatSpec(2, class_mode='any', match=RepeatMatchSpec(recipient_cost=RepeatCostFilter('local', maximum=2)))
        self.r.register_card(CardDefinition('repeat', 'repeat', CardType.MINION, health=5,
            metadata=fixtures.metadata(), spell_repeats=(spec,)))
        g = self.game(('arcane', 'intrinsic-spell'), board=('repeat',))
        self.play(g, 'arcane'); self.end(g); self.end(g); self.play(g, 'intrinsic-spell')
        play = g.state.play_history[-1]
        facts = play.spell_payload.cost_facts
        self.assertEqual((facts.local_amount, facts.window_quotes, facts.intrinsic.amount), (2, (), 2))
        self.assertEqual(play.spell_payload.casts, 2)
        self.portable(g)

    def test_required_wire_and_false_row_tampering_are_rejected(self):
        g = self.closed_arcane('intrinsic-spell')
        self.play(g, 'intrinsic-spell')
        saved = self.portable(g)
        del saved['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
        self.reject(saved)
        saved = g.snapshot()
        stage = saved['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
        stage['condition_facts'][0]['rows'][0]['matched'] = False
        stage['condition_facts'][0]['matched'] = False
        stage['operations'][0]['applied'] = False
        stage['operations'][0]['after'] = 5
        stage['amount'] = 5
        self.reject(saved)

    def test_unknown_static_policy_rejected_before_matching(self):
        with self.assertRaises(ValueError): IntrinsicCostSpec(condition='unimplemented')
        with self.assertRaises(ValueError): IntrinsicCostSpec(delta=True)
        with self.assertRaises(ValueError): self.r.register_card(replace(self.r.card('intrinsic-spell'),
            id='bad', intrinsic_costs=[IntrinsicCostSpec()]))

    def test_same_rule_set_precedes_delta_and_reduction_floor_is_pure(self):
        rules = (IntrinsicCostSpec(set_to=1, delta=10, minimum=2),
                 IntrinsicCostSpec(delta=-6, minimum=5),
                 IntrinsicCostSpec(delta=1))
        for card, school in (('same-rule-arcane', SpellSchool.ARCANE),
                             ('same-rule-frost', SpellSchool.FROST)):
            self.r.register_card(replace(self.r.card('intrinsic-spell'),
                id=card, name=card, spell_school=school, intrinsic_costs=rules))
        g = self.closed_arcane('same-rule-arcane', 'same-rule-frost')
        before_state = deepcopy(g.state)
        before_snapshot = g.snapshot()
        for card, matched, expected, operations in (
            ('same-rule-arcane', True, 3, ((5, 2), (2, 2), (2, 3))),
            ('same-rule-frost', False, 5, ((5, 5), (5, 5), (5, 5))),
        ):
            with self.subTest(card=card):
                physical = self.fact(g, card)
                generated = capture_generated_quote_fact(g.state, self.r, 1, card)
                self.assertEqual(physical.intrinsic, generated.intrinsic)
                self.assertEqual((physical.local_amount, physical.amount,
                                  generated.local_amount, generated.amount),
                                 (expected, expected, expected, expected))
                self.assertEqual(quote_cost(g.state, self.r, self.source(g, card)).amount, expected)
                self.assertEqual(quote_generated_cost(g.state, self.r, 1, card).amount, expected)
                for stage in (physical.intrinsic, generated.intrinsic):
                    self.assertEqual(stage.rules, rules)
                    self.assertEqual((stage.printed_cost, stage.base_cost, stage.amount), (5, 5, expected))
                    self.assertEqual(stage.boundary.play_history_length, 1)
                    condition, = stage.condition_facts
                    self.assertEqual(condition.owner_turn, g.state.owner_turn_history[0])
                    self.assertIs(condition.matched, matched)
                    row, = condition.rows
                    self.assertEqual(row.face, g.state.play_history[0].played_face)
                    self.assertIs(row.matched, matched)
                    self.assertEqual(tuple((o.rule_index, o.spec, o.condition_index,
                                            o.applied, o.before, o.after) for o in stage.operations),
                                     tuple((i, rules[i], 0, matched, before, after)
                                           for i, (before, after) in enumerate(operations)))
                    validate_intrinsic_stage_fact(self.r, stage)
                    validate_intrinsic_origin(stage, g.state, self.r)
                validate_generated_quote_fact(self.r, generated)
        self.assertEqual(g.state, before_state)
        self.assertEqual(g.snapshot(), before_snapshot)



if __name__ == '__main__': unittest.main()
