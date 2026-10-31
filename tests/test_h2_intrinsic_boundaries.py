"""Actual account, window, retry and privacy boundaries for isolated H2.

Fixtures use public actions/effects. Malformed values are detached copies of
actual paid Spell proofs; no synthetic turn ledger or payment is installed.
"""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

import test_m5_owner_turn_history as history_fixtures
from hs_sim.engine import (CardDefinition, CardType, Game, IntrinsicCostSpec,
    Keyword, PlayerSetup, RewindSpec, Scenario, SnapshotError, SpellSchool,
    TriggerSpec)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_generated_quote_fact
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, GainArmor,
    ModifyCost, RequestChoice)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_stage_fact)
from hs_sim.engine.model import (CostSpec, PaymentType, RecipientMetadataFilter,
    RepeatCostFilter, RepeatMatchSpec, Resource, SpellRepeatSpec)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_acceptance import FinishSpellAcceptance, validate_acceptance
from hs_sim.engine.spell_cost_proof import (validate_hand_cost_proof,
    validate_hand_cost_proof_live)
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier


ASK = 'boundary.ask'
REWIND_ONE = 'boundary.rewind1'
REWIND_ZERO = 'boundary.rewind0'
RETAINED = 'boundary.retained'
WINDOW_SETUP = 'boundary.prepare.windows'
REWIND_SETUP = 'boundary.prepare.rewind'


def ask_body(context):
    return [RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Continue paid Spell', (GainArmor(context.player_id, 1),)),),
        source_id=context.source_id)]


def rewind_body(context):
    return [RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Continue retry outcome',
            (GainArmor(context.player_id, context.rewind_attempt + 1),)),),
        source_id=context.source_id)]


def subject_in_hand(context, card_id):
    return next(identity for identity in context.state.players[context.player_id].hand
        if context.state.entities[identity].card_id == card_id)


def account_prepare(context, payment):
    identity = subject_in_hand(context, ASK)
    return [ModifyCost(identity, CostSpec(payment=payment)),
        AddCostModifier(context.player_id, CostSpec(delta=-1, card_ids=(ASK,)),
            uses_remaining=1)]


def window_repeat(casts):
    return SpellRepeatSpec(casts, 'any', RepeatMatchSpec(
        recipient_metadata=RecipientMetadataFilter(spell_schools=(SpellSchool.ARCANE,)),
        recipient_cost=RepeatCostFilter('window_quote', maximum=2,
            quote_profile_id='repeat.cost.accepted_hand')))


def prepare_windows(context):
    return [*account_prepare(context, PaymentType.MANA),
        AddSpellRepeatModifier(context.player_id, window_repeat(2), uses=1)]


def payment_window_reaction(context):
    identity = context.event.source_id
    if identity is None or context.state.entities[identity].card_id != ASK:
        return []
    return [ModifyCost(identity, CostSpec(set_to=4)),
        RequestChoice(context.player_id,
            (ChoiceOption('ok', 'Continue after payment reaction'),), source_id=identity)]


def prepare_rewind(context):
    return [AddCostModifier(context.player_id,
        CostSpec(delta=-1, card_ids=(REWIND_ONE, RETAINED)), uses_remaining=1)]


def registry():
    result = history_fixtures.registry()
    result.register_behavior('boundary.ask.body', ask_body)
    result.register_behavior('boundary.rewind.body', rewind_body)
    common = dict(cost=5, spell_school=SpellSchool.ARCANE,
        metadata=history_fixtures.metadata(), intrinsic_costs=(IntrinsicCostSpec(delta=-3),))
    result.register_card(CardDefinition(ASK, ASK, CardType.SPELL,
        on_play='boundary.ask.body', **common))
    for identity, spec, keywords in (
            (REWIND_ONE, RewindSpec(1, REWIND_ZERO), (Keyword.REWIND,)),
            (REWIND_ZERO, None, ()),
            (RETAINED, RewindSpec(1), (Keyword.REWIND,))):
        result.register_card(CardDefinition(identity, identity, CardType.SPELL,
            on_play='boundary.rewind.body', rewind=spec, keywords=keywords, **common))
    result.register_card(CardDefinition('boundary.zero-minion', 'boundary.zero-minion',
        CardType.MINION, cost=0, attack=1, health=5,
        metadata=history_fixtures.metadata(('dragon',)),
        intrinsic_costs=(IntrinsicCostSpec(delta=-3),)))
    for payment in PaymentType:
        identity = 'boundary.prepare.' + payment.value
        result.register_behavior(identity,
            lambda context, payment=payment: account_prepare(context, payment))
        result.register_card(CardDefinition(identity, identity, CardType.SPELL,
            on_play=identity, metadata=history_fixtures.metadata()))
    for identity, behavior in ((WINDOW_SETUP, prepare_windows),
            (REWIND_SETUP, prepare_rewind)):
        result.register_behavior(identity, behavior)
        result.register_card(CardDefinition(identity, identity, CardType.SPELL,
            on_play=identity, metadata=history_fixtures.metadata()))
    result.register_behavior('boundary.payment.watch', payment_window_reaction)
    result.register_card(CardDefinition('boundary.payment.watch', 'boundary.payment.watch',
        CardType.MINION, health=5, metadata=history_fixtures.metadata(),
        triggers=(TriggerSpec('mana_spent', 'boundary.payment.watch'),)))
    result.register_card(CardDefinition('boundary.window.repeat', 'boundary.window.repeat',
        CardType.MINION, health=5, metadata=history_fixtures.metadata(),
        spell_repeats=(window_repeat(3),)))
    return result


class IntrinsicBoundaryTests(unittest.TestCase):
    play = history_fixtures.OwnerTurnActionTests.play
    end = history_fixtures.OwnerTurnActionTests.end
    choose = history_fixtures.OwnerTurnActionTests.choose

    def setUp(self):
        self.r = registry()

    def game(self, hand=(), enemy_hand=(), *, board=(), armor=0, corpses=0):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero1', hand=hand, board=board, deck=('empty',) * 12,
                max_mana=10, mana=10, armor=armor, corpses=corpses),
            PlayerSetup('hero2', hand=enemy_hand, deck=('empty',) * 12,
                max_mana=10, mana=10)), seed=5118), self.r)

    def closed_arcane(self, *hand, board=(), armor=0, corpses=0):
        game = self.game(('frost', 'arcane', *hand), board=board,
            armor=armor, corpses=corpses)
        self.play(game, 'frost')
        self.play(game, 'arcane')
        self.end(game)
        self.end(game)
        return game

    def fresh_registry(self):
        result = registry()
        self.assertIsNot(result, self.r)
        self.assertEqual(result.fingerprint(), self.r.fingerprint())
        return result

    def portable(self, game):
        snapshot = json.loads(json.dumps(game.snapshot(), ensure_ascii=False))
        restored = Game.from_snapshot(snapshot, self.fresh_registry())
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), self.fresh_registry()).snapshot(), snapshot)
        return restored

    def reject_snapshot(self, snapshot):
        snapshot['state_hash'] = canonical_hash({key: value for key, value in snapshot.items()
            if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as raised:
            Game.from_snapshot(snapshot, self.fresh_registry())
        self.assertNotIn('digest mismatch', str(raised.exception))

    def complete(self, game):
        count = 0
        while game.state.pending_choice:
            self.assertLess(count, 8, 'Fixture unexpectedly produced additional choices')
            self.choose(game)
            count += 1
        return count

    def proof(self, game):
        proofs = [work for work in (*game._frame.prefix, *game._frame.continuation)
            if type(work) is FinishSpellAcceptance]
        self.assertEqual(len(proofs), 1)
        return proofs[0]

    def source(self, game, identity, player=1):
        return next(entity_id for entity_id in game.state.players[player].hand
            if game.state.entities[entity_id].card_id == identity)

    def without_false_row(self, stage):
        condition, = stage.condition_facts
        self.assertEqual(tuple(row.matched for row in condition.rows), (False, True))
        shorter = replace(condition, rows=tuple(row for row in condition.rows if row.matched))
        return replace(stage, condition_facts=(shorter,))

    def test_four_real_accounts_keep_local_override_and_one_finite_external_use(self):
        # Opponent-health payment has its own bounded-source card suite.
        for payment in (PaymentType.MANA, PaymentType.HEALTH, PaymentType.ARMOR, PaymentType.CORPSES):
            with self.subTest(payment=payment):
                setup = 'boundary.prepare.' + payment.value
                game = self.closed_arcane(setup, ASK,
                    armor=3 if payment == PaymentType.ARMOR else 0,
                    corpses=3 if payment == PaymentType.CORPSES else 0)
                self.play(game, setup)
                before = game.state
                hero = before.entities[before.players[1].hero_id]
                old = (before.players[1].mana, hero.health, hero.armor,
                    before.players[1].resources[Resource.CORPSES])
                source = self.play(game, ASK)
                play = game.state.play_history[-1]
                quote = play.submitted_cost.quote
                self.assertEqual((quote.intrinsic.amount, quote.local_amount, quote.amount), (2, 2, 1))
                self.assertEqual((play.cost, play.payment, quote.local_payment, quote.payment),
                    (1, payment, payment, payment))
                self.assertEqual(tuple(row.matched for row in quote.intrinsic.condition_facts[0].rows),
                    (False, True))
                self.assertEqual(len(quote.consumable_ids), 1)
                self.assertFalse(game.state.players[1].cost_modifiers)
                current = game.state
                hero = current.entities[current.players[1].hero_id]
                actual = (current.players[1].mana, hero.health, hero.armor,
                    current.players[1].resources[Resource.CORPSES])
                expected = list(old)
                expected[{PaymentType.MANA: 0, PaymentType.HEALTH: 1,
                    PaymentType.ARMOR: 2, PaymentType.CORPSES: 3}[payment]] -= 1
                self.assertEqual(actual, tuple(expected))
                validate_acceptance(self.proof(game), self.r)
                restored = self.portable(game)
                self.assertEqual(self.complete(game), 1)
                self.assertEqual(self.complete(restored), 1)
                self.assertEqual(restored.snapshot(), game.snapshot())
                uses = [row for row in game.state.cost_use_history if row.source_id == source]
                spent = [event for event in game.events
                    if event.kind == payment.value + '_spent' and event.source_id == source]
                self.assertEqual((len(uses), len(spent)), (1, 1))
                self.assertEqual((uses[0].amount, uses[0].payment, uses[0].consumable_ids),
                    (1, payment, quote.consumable_ids))

    def test_two_spell_windows_keep_distinct_required_stages_after_actual_payment_reaction(self):
        game = self.closed_arcane(WINDOW_SETUP, ASK,
            board=('boundary.payment.watch', 'boundary.window.repeat'))
        self.play(game, WINDOW_SETUP)
        self.play(game, ASK)
        initial = game.state.play_history[-1]
        submission = initial.spell_submission.cost_facts
        self.assertEqual((initial.cost, submission.window_quotes[0].amount), (1, 2))
        self.assertIsNone(self.proof(game).resolution)
        self.assertEqual(submission.intrinsic, submission.window_quotes[0].intrinsic)
        self.portable(game)
        self.choose(game)
        current = game.state.play_history[-1]
        payload = current.spell_payload.cost_facts
        self.assertEqual((payload.local_amount, payload.window_quotes[0].amount), (4, 4))
        self.assertEqual((submission.intrinsic.amount, payload.intrinsic.amount), (2, 2))
        self.assertEqual(payload.intrinsic, payload.window_quotes[0].intrinsic)
        self.assertEqual(submission.intrinsic.condition_facts, payload.intrinsic.condition_facts)
        self.assertLess(submission.intrinsic.boundary.action, payload.intrinsic.boundary.action)
        self.assertNotEqual(submission, payload)
        self.assertEqual(current.spell_payload.casts, 2)
        self.assertFalse(current.spell_payload.contributors)
        self.assertFalse(game.state.players[1].spell_modifiers)
        validate_acceptance(self.proof(game), self.r)
        restored = self.portable(game)
        self.assertEqual(self.complete(game), 2)
        self.assertEqual(self.complete(restored), 2)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(game.state.play_history[-1].submitted_cost.quote.amount, 1)

    def test_generated_typed_codec_replays_complete_algebra_without_state_or_source(self):
        game = self.closed_arcane('boundary.prepare.mana', ASK)
        self.play(game, 'boundary.prepare.mana')
        before = game.snapshot()
        fact = capture_generated_quote_fact(game.state, self.r, 1, ASK,
            cost=CostSpec(set_to=4, payment=PaymentType.HEALTH), minimum_cost=6)
        self.assertEqual((fact.intrinsic.amount, fact.local_amount, fact.amount), (2, 4, 6))
        self.assertEqual(fact.payment, PaymentType.HEALTH)
        self.assertEqual(len(fact.consumable_ids), 1)
        self.assertFalse(hasattr(fact.quote_input, 'source_id'))
        codec = FrameCodec(game.mechanics, self.r, origin_state=game.state)
        wire = codec.encode(fact)
        self.assertEqual(codec.decode(json.loads(json.dumps(wire))), fact)
        validate_generated_quote_fact(self.r, fact)
        malformed = replace(fact, amount=7)
        malformed.__post_init__()
        with self.assertRaises(ValueError): validate_generated_quote_fact(self.r, malformed)
        with self.assertRaises(ValueError): codec.encode(malformed)
        changed = deepcopy(wire)
        changed['fields']['amount'] = 7
        with self.assertRaises(ValueError): codec.decode(changed)
        missing = deepcopy(wire)
        del missing['fields']['intrinsic']
        with self.assertRaises(ValueError): codec.decode(missing)
        future = deepcopy(fact)
        boundary = future.intrinsic.boundary
        future_owner = replace(boundary.last_owner_turn,
            publication_action=boundary.action + 1)
        object.__setattr__(boundary, 'last_owner_turn', future_owner)
        with self.assertRaises(ValueError): validate_generated_quote_fact(self.r, future)
        with self.assertRaises(ValueError): codec.encode(future)
        future_wire = deepcopy(wire)
        future_wire['fields']['intrinsic']['fields']['boundary']['fields'][
            'last_owner_turn']['fields']['publication_action'] = fact.intrinsic.boundary.action + 1
        with self.assertRaises(ValueError): codec.decode(future_wire)
        self.assertEqual(game.snapshot(), before)
        self.play(game, ASK)
        self.assertIsNotNone(game.state.pending_choice)
        waiting_before = game.snapshot()
        waiting = capture_generated_quote_fact(game.state, self.r, 1, ASK,
            cost=CostSpec(set_to=4, payment=PaymentType.HEALTH), minimum_cost=6)
        waiting_codec = FrameCodec(game.mechanics, self.r, origin_state=game.state)
        validate_generated_quote_fact(self.r, waiting)
        self.assertEqual(waiting_codec.decode(waiting_codec.encode(waiting)), waiting)
        self.assertEqual(game.snapshot(), waiting_before)
        self.choose(game)
        later = capture_generated_quote_fact(game.state, self.r, 1, ASK,
            cost=CostSpec(set_to=4, payment=PaymentType.HEALTH), minimum_cost=6)
        later_codec = FrameCodec(game.mechanics, self.r, origin_state=game.state)
        validate_generated_quote_fact(self.r, later)
        self.assertEqual(later_codec.decode(later_codec.encode(later)), later)
        self.assertEqual((waiting.amount, later.amount), (6, 6))
        self.assertLess(waiting.intrinsic.boundary.action, later.intrinsic.boundary.action)

    def test_real_spell_retry_keeps_original_intrinsic_quote_and_exact_live_anchor(self):
        game = self.closed_arcane(REWIND_SETUP, REWIND_ONE)
        self.play(game, REWIND_SETUP)
        source = self.play(game, REWIND_ONE)
        initial = self.proof(game).cost_proof
        self.assertEqual((initial.rewind_session.attempt, initial.rewind_anchor), (0, None))
        self.assertEqual(initial.prepared_play.submitted_cost.quote.amount, 1)
        self.portable(game)
        self.choose(game)
        self.assertEqual(game.state.pending_choice.purpose.value, 'rewind')
        self.portable(game)
        self.choose(game, 'retry')
        cost_proof = self.proof(game).cost_proof
        receipt = game.state.play_history[-1].submitted_cost
        self.assertEqual((cost_proof.rewind_session.attempt, cost_proof.rewind_anchor.attempt), (1, 1))
        self.assertEqual((receipt.quote_origin, receipt.quote.amount,
            receipt.quote.quote_input.card_id, receipt.quote.intrinsic.card_id),
            ('rewind_root', 1, REWIND_ONE, REWIND_ONE))
        self.assertEqual((cost_proof.prepared_play.card_id,
            cost_proof.payment_state.entities[source].card_id), (REWIND_ZERO, REWIND_ZERO))
        self.assertEqual(cost_proof.rewind_anchor.before.entities[source].card_id, REWIND_ONE)
        validate_hand_cost_proof(cost_proof, self.r)
        validate_hand_cost_proof_live(cost_proof, game)
        before = game.snapshot()
        ordinary = replace(cost_proof, rewind_anchor=None, rewind_session=None)
        with self.assertRaises(ValueError): validate_hand_cost_proof_live(ordinary, game)
        self.assertEqual(game.snapshot(), before)
        restored = self.portable(game)
        self.assertEqual(self.complete(game), 1)
        self.assertEqual(self.complete(restored), 1)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual((game.state.players[1].mana,
            game.state.entities[game.state.players[1].hero_id].armor), (9, 2))
        self.assertEqual(len([row for row in game.state.cost_use_history if row.source_id == source]), 1)
        self.assertEqual(len([row for row in game.state.play_history if row.source_id == source]), 1)
        self.assertEqual(len([event for event in game.events
            if event.kind == 'mana_spent' and event.source_id == source]), 2)
        self.assertEqual(sum(event.kind == 'timeline_rewound' for event in game.events), 1)

    def test_retained_spell_outcomes_share_one_intrinsic_payment_and_submission(self):
        game = self.closed_arcane(REWIND_SETUP, RETAINED, board=('retainer',))
        self.play(game, REWIND_SETUP)
        source = self.play(game, RETAINED)
        original = game.state.play_history[-1].submitted_cost
        self.assertEqual((original.quote.amount, original.quote.intrinsic.amount), (1, 2))
        self.assertEqual(self.proof(game).cost_proof.rewind_session.attempt, 0)
        restored = self.portable(game)
        self.choose(game)
        self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(game.state.play_history[-1].submitted_cost, original)
        validate_acceptance(self.proof(game), self.r)
        self.portable(game)
        self.choose(game)
        self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertIsNone(game.state.pending_choice)
        self.assertEqual((game.state.players[1].mana,
            game.state.entities[game.state.players[1].hero_id].armor), (9, 3))
        play = game.state.play_history[-1]
        self.assertEqual(play.submitted_cost, original)
        self.assertEqual(len([row for row in game.state.play_history if row.source_id == source]), 1)
        self.assertEqual(len([row for row in game.state.cast_history if row.play_id == play.id]), 1)
        self.assertEqual(len([row for row in game.state.cost_use_history if row.source_id == source]), 1)
        self.assertEqual(len([event for event in game.events
            if event.kind == 'mana_spent' and event.source_id == source]), 1)
        self.assertFalse(any(event.kind == 'timeline_rewound' for event in game.events))
        retained = [row for row in game.state.rewind_outcomes if row.play_id == play.id]
        self.assertEqual(len(retained), 1)
        self.assertEqual((retained[0].completed, retained[0].finished), (2, True))
        self.portable(game)

    def test_both_seats_quote_their_own_history_without_enemy_or_private_fact_leaks(self):
        game = self.game(('frost', 'arcane', ASK), ('frost', ASK))
        self.play(game, 'frost')
        self.play(game, 'arcane')
        self.end(game)
        self.play(game, 'frost')
        self.end(game)
        before = game.snapshot()
        for seat, amount in ((1, 2), (2, 5)):
            view = game.for_player(seat).observe()['observation']
            own = next(player for player in view['players'] if player['id'] == seat)
            enemy = next(player for player in view['players'] if player['id'] != seat)
            subject = next(row for row in own['hand'] if row.get('card_id') == ASK)
            self.assertEqual(subject['cost'], {'amount': amount, 'payment': 'mana'})
            for row in enemy['hand']:
                self.assertNotIn('cost', row)
                self.assertIsNone(row['card_id'])
            encoded = json.dumps(view, ensure_ascii=False)
            for private in ('intrinsic', 'condition_facts', 'owner_turn_history',
                    'played_face', 'payment_state', 'submitted_cost', 'consumable_ids'):
                self.assertNotIn(private, encoded)
            encoded_events = json.dumps(game.for_player(seat).events(), ensure_ascii=False)
            self.assertNotIn('condition_facts', encoded_events)
            self.assertNotIn('payment_state', encoded_events)
        self.assertEqual(game.snapshot(), before)

    def test_actual_prepaid_proof_rejects_deleted_false_row_with_unchanged_price(self):
        game = self.closed_arcane(ASK)
        self.play(game, ASK)
        cost_proof = self.proof(game).cost_proof
        original_quote = cost_proof.prepared_play.submitted_cost.quote
        shorter = self.without_false_row(original_quote.intrinsic)
        validate_intrinsic_stage_fact(self.r, shorter)
        malformed_quote = replace(original_quote, intrinsic=shorter)
        receipt = replace(cost_proof.prepared_play.submitted_cost, quote=malformed_quote)
        prepared = replace(cost_proof.prepared_play, submitted_cost=receipt)
        malformed_proof = replace(cost_proof, prepared_play=prepared)
        self.assertEqual(malformed_quote.amount, original_quote.amount)
        before = game.snapshot()
        with self.assertRaises(ValueError): validate_hand_cost_proof(malformed_proof, self.r)
        validate_hand_cost_proof(cost_proof, self.r)
        saved = deepcopy(before)
        relation = saved['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['condition_facts'][0]
        relation['rows'] = [row for row in relation['rows'] if row['matched']]
        self.reject_snapshot(saved)
        self.assertEqual(game.snapshot(), before)

    def test_actual_late_window_rejects_false_row_removal_and_zero_never_hides_unknown(self):
        game = self.closed_arcane(WINDOW_SETUP, ASK,
            board=('boundary.payment.watch', 'boundary.window.repeat'))
        self.play(game, WINDOW_SETUP)
        self.play(game, ASK)
        self.choose(game)
        proof = self.proof(game)
        self.assertIsNone(proof.resolution.play.spell_payload)
        facts = game.state.play_history[-1].spell_payload.cost_facts
        shorter = self.without_false_row(facts.intrinsic)
        validate_intrinsic_stage_fact(self.r, shorter)
        altered_facts = replace(facts, intrinsic=shorter,
            window_quotes=tuple(replace(quote, intrinsic=shorter) for quote in facts.window_quotes))
        from hs_sim.engine.repeat_matching import validate_spell_cost_facts
        validate_spell_cost_facts(self.r, altered_facts)
        self.assertEqual((altered_facts.local_amount, altered_facts.local_payment),
            (facts.local_amount, facts.local_payment))
        self.assertEqual(tuple((quote.amount, quote.payment) for quote in altered_facts.window_quotes),
            tuple((quote.amount, quote.payment) for quote in facts.window_quotes))
        before = game.snapshot()
        saved = deepcopy(before)
        saved_facts = saved['state']['play_history'][-1]['spell_payload']['cost_facts']
        for intrinsic in (saved_facts['intrinsic'],
                *(quote['intrinsic'] for quote in saved_facts['window_quotes'])):
            relation = intrinsic['condition_facts'][0]
            relation['rows'] = [row for row in relation['rows'] if row['matched']]
        self.reject_snapshot(saved)
        validate_acceptance(proof, self.r)
        self.assertEqual(game.snapshot(), before)
        unknown = self.game(('dragon', 'unknown', 'boundary.zero-minion'))
        self.play(unknown, 'dragon')
        self.play(unknown, 'unknown')
        self.end(unknown)
        self.end(unknown)
        source = self.source(unknown, 'boundary.zero-minion')
        self.assertEqual(unknown.state.entities[source].base_cost, 0)
        unchanged = unknown.snapshot()
        with self.assertRaisesRegex(ValueError, 'known Minion tribes'):
            unknown.quote_cost(source)
        self.assertEqual(unknown.snapshot(), unchanged)
        with self.assertRaisesRegex(ValueError, 'known Minion tribes'):
            self.play(unknown, 'boundary.zero-minion')
        self.assertEqual(unknown.snapshot(), unchanged)


if __name__ == '__main__':
    unittest.main()
