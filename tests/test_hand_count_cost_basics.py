"""Pure hand-count prices with frozen real payments and private inventories."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardDefinition, CardType, CostSpec,
    Game, HandCountCostSpec, IllegalAction, InteractableSpec, PlayCard, PlayerSetup,
    Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact,
    capture_quote_fact, quote_cost, quote_generated_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption,
    CopyMinion, Draw, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_history_prefix, validate_intrinsic_origin,
    validate_intrinsic_stage_fact)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, DiscardCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


MOUNTAIN = 'EX1_105'
CLOCKWORK = 'GVG_121'
LOW = 'hand.low'
PATH = Path(__file__).resolve().parents[1] / 'data/support/hand-count-cost-basics.json'
PIN = 'a55951de85fa213a7046d60c5c0501b88a042166d9e1d7d700eee1b8992b60e4'


def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN:
        raise ValueError('Hand count evidence changed')
    rows = {}
    for item in support['records']:
        if canonical_digest(item['data']) != item['data_sha256']:
            raise ValueError('Hand count complete raw changed')
        rows[item['id']] = item['data']
    return rows


def registry():
    r = opening_registry()
    raw = evidence()
    for cid, scope, tribe in ((MOUNTAIN, 'friendly_other', 'elemental'), (CLOCKWORK, 'enemy', 'mech')):
        row = raw[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION,
            cost=row['cost'], attack=row['attack'], health=row['health'],
            metadata=metadata(rarity=Rarity.EPIC, tribes=(tribe,)),
            hand_count_cost=HandCountCostSpec(scope)))
    r.register_card(CardDefinition(LOW, 'Synthetic low hand-count fixture', CardType.MINION,
        cost=2, attack=1, health=2, hand_count_cost=HandCountCostSpec()))
    r.register_card(CardDefinition('hand.weapon', 'Held weapon fixture', CardType.WEAPON,
        attack=1, durability=1, metadata=metadata()))
    r.register_behavior('hand.inert', lambda c: ())

    def held(c, cid):
        return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == cid)

    def first(c):
        return c.state.players[c.player_id].board[0]

    def discard(c, player):
        return DiscardCard(CardReference.capture(c.state.entities[c.state.players[player].hand[0]]))

    scripts = {
        'hand.draw': lambda c: (Draw(c.player_id, 2),),
        'hand.discard': lambda c: (discard(c, c.player_id),),
        'hand.enemy.draw': lambda c: (Draw(3 - c.player_id, 2),),
        'hand.enemy.add': lambda c: (AddToHand(3 - c.player_id, 'card.4'),),
        'hand.enemy.discard': lambda c: (discard(c, 3 - c.player_id),),
        'hand.copy': lambda c: (CopyMinion(first(c), c.player_id, mode='base'),),
        'hand.silence': lambda c: (Silence(first(c)),),
        'hand.bounce': lambda c: (ReturnToHand(first(c)),),
        'hand.local': lambda c: (ModifyCost(held(c, MOUNTAIN), CostSpec(delta=-3)),),
        'hand.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(MOUNTAIN,))),),
        'hand.fail': lambda c: (AddToHand(c.player_id, 'card.4'), AddToHand(3 - c.player_id, 'unknown.hand.count')),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))

    def pause(c):
        if c.state.entities[c.event.source_id].card_id != MOUNTAIN:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('refill', 'Acquire one card', (AddToHand(c.player_id, 'card.4'),)),
            ChoiceOption('fault', 'Delayed fixture failure', (InvokeBehavior('hand.fail', c.source_id, c.player_id),)),
        ), c.source_id),)

    r.register_behavior('hand.pause', pause)
    r.register_card(CardDefinition('hand.watch', 'Paid completion observer', CardType.MINION,
        attack=1, health=3, triggers=(TriggerSpec('card_played', 'hand.pause'),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class HandCountCostTests(unittest.TestCase):
    def game(self, hand=(MOUNTAIN, CLOCKWORK), *, enemy_hand=(), board=(), deck=(), enemy_deck=(), mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=deck, mana=mana, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, deck=enemy_deck)), seed=17), registry())

    def source(self, g, cid=MOUNTAIN, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)

    def fact(self, g, cid=MOUNTAIN, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))

    def price(self, g, cid=MOUNTAIN, player=1):
        return self.fact(g, cid, player).amount

    def play(self, g, cid):
        eid = self.source(g, cid).id
        g.apply(PlayCard(1, eid))
        return eid

    def choose(self, g, option='refill'):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry())
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for player in (1, 2):
            self.assertEqual(restored.observe(player), g.observe(player))
        return saved

    def test_three_complete_raw_records_and_two_real_count_formulas_are_pinned(self):
        rows = evidence()
        original = {row['id']: row for row in json.loads((PATH.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8'))}
        self.assertEqual(set(rows), {MOUNTAIN, 'CORE_EX1_105', CLOCKWORK})
        for cid, row in rows.items():
            self.assertEqual(row, original[cid])
            self.assertEqual((row['cost'], row['attack'], row['health']), (12, 8, 8))
        self.assertIn('each other card in your hand', rows[MOUNTAIN]['text_en'])
        self.assertIn("each card in your opponent's hand", rows[CLOCKWORK]['text_en'])

    def test_only_finite_scopes_and_ordinary_minion_declarations_are_accepted(self):
        for scope in (True, None, 'all', 'formula'):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                HandCountCostSpec(scope)
        with self.assertRaises(ValueError):
            HandCountCostSpec(profile_id='unknown')
        r = registry()
        for changes in ({'kind': CardType.HERO, 'health': 0}, {'hand_count_cost': 'expression'},
                {'interactable': InteractableSpec('hand.inert')}, {'board_minion_cost': BoardMinionCostSpec()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                r.register_card(replace(r.card(MOUNTAIN), id='bad.hand.count', **changes))

    def test_own_other_count_excludes_only_the_physical_subject_not_all_equal_names(self):
        g = self.game(hand=(MOUNTAIN, MOUNTAIN, 'card.1'))
        first = self.source(g)
        f = self.fact(g).intrinsic.hand_cards
        self.assertEqual((f.quantity, f.after, self.price(g)), (2, 10, 10))
        self.assertEqual(f.subject_id, first.id)
        self.assertEqual(f.hands, (tuple(g.state.players[1].hand), ()))
        second = g.state.entities[g.state.players[1].hand[1]]
        self.assertEqual(quote_cost(g.state, g.registry, second).amount, 10)
        self.portable(g)

    def test_opponent_count_includes_all_card_types_and_ignores_own_hand_size(self):
        g = self.game(hand=(CLOCKWORK,), enemy_hand=(MOUNTAIN, 'coin', 'hand.weapon'))
        f = self.fact(g, CLOCKWORK).intrinsic.hand_cards
        self.assertEqual((f.quantity, f.after, self.price(g, CLOCKWORK)), (3, 9, 9))
        self.assertEqual(tuple(map(len, f.hands)), (1, 3))
        self.portable(g)

    def test_both_scopes_use_the_actual_payer(self):
        g = self.game(hand=(MOUNTAIN, CLOCKWORK, 'card.1'), enemy_hand=(MOUNTAIN, CLOCKWORK))
        self.assertEqual((self.price(g), self.price(g, MOUNTAIN, 2)), (10, 11))
        self.assertEqual((self.price(g, CLOCKWORK), self.price(g, CLOCKWORK, 2)), (10, 9))
        self.assertEqual(self.fact(g, MOUNTAIN, 2).intrinsic.hand_cards.subject_id, self.source(g, MOUNTAIN, 2).id)

    def test_subject_outside_hand_has_no_exclusion_and_board_or_deck_cards_do_not_count(self):
        g = self.game(hand=('card.1',), board=(MOUNTAIN,), deck=('card.2',))
        subject = g.state.entities[g.state.players[1].board[0]]
        f = capture_quote_fact(g.state, g.registry, capture_cost_input(subject))
        self.assertEqual((f.amount, f.intrinsic.hand_cards.quantity), (11, 1))
        self.assertNotIn(subject.id, f.intrinsic.hand_cards.hands[0])
        self.assertEqual(quote_generated_cost(g.state, g.registry, 1, MOUNTAIN).amount, 11)

    def test_generated_subject_is_an_additional_card_and_never_borrows_held_identity(self):
        g = self.game(hand=(MOUNTAIN, 'card.1'), enemy_hand=('card.2', 'coin'))
        before = g.snapshot()
        f = capture_generated_quote_fact(g.state, g.registry, 1, MOUNTAIN)
        self.assertEqual((self.price(g), f.amount, f.intrinsic.hand_cards.quantity), (11, 10, 2))
        self.assertIsNone(f.intrinsic.hand_cards.subject_id)
        validate_generated_quote_fact(g.registry, f)
        self.assertEqual(quote_generated_cost(g.state, g.registry, 1, CLOCKWORK).amount, 10)
        self.assertEqual(g.snapshot(), before)

    def test_full_hand_physical_and_hypothetical_quotes_use_distinct_other_counts(self):
        g = self.game(hand=(MOUNTAIN, *tuple(f'card.{i}' for i in range(1, 10))))
        self.assertEqual(self.price(g), 3)
        self.assertEqual(quote_generated_cost(g.state, g.registry, 1, MOUNTAIN).amount, 2)
        self.assertEqual(len(g.state.players[1].hand), 10)

    def test_zero_floor_and_repeated_quotes_do_not_write_state_rng_ids_or_modifiers(self):
        g = self.game(hand=(LOW, 'card.1', 'coin'), mana=0)
        before = g.snapshot()
        for _ in range(3):
            self.assertEqual(self.price(g, LOW), 0)
            self.assertEqual(quote_generated_cost(g.state, g.registry, 1, LOW).amount, 0)
            g.for_player(1).legal_actions()
        self.assertEqual(g.snapshot(), before)
        self.play(g, LOW)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (0, 0))
        self.portable(g)

    def test_actual_draw_discard_and_play_requote_instead_of_installing_cost_edits(self):
        g = self.game(hand=('card.1', MOUNTAIN, 'hand.draw', 'hand.discard'), deck=('card.2', 'card.3'))
        self.assertEqual(self.price(g), 9)
        self.play(g, 'hand.draw')
        self.assertEqual(self.price(g), 8)
        self.play(g, 'hand.discard')
        self.assertEqual(self.price(g), 10)
        self.play(g, 'card.2')
        self.assertEqual(self.price(g), 11)
        subject = self.source(g)
        self.assertEqual((subject.base_cost, subject.cost_modifier, subject.enchantments), (12, 0, []))
        self.portable(g)

    def test_opponent_draw_acquisition_and_discard_requote_from_current_opponent_hand(self):
        g = self.game(hand=(CLOCKWORK, 'hand.enemy.draw', 'hand.enemy.add', 'hand.enemy.discard'),
            enemy_hand=('card.1',), enemy_deck=('card.2', 'card.3'))
        self.assertEqual(self.price(g, CLOCKWORK), 11)
        self.play(g, 'hand.enemy.draw')
        self.assertEqual(self.price(g, CLOCKWORK), 9)
        self.play(g, 'hand.enemy.add')
        self.assertEqual(self.price(g, CLOCKWORK), 8)
        self.play(g, 'hand.enemy.discard')
        self.assertEqual(self.price(g, CLOCKWORK), 9)
        self.portable(g)

    def test_burned_acquisition_does_not_increase_opponent_hand_quantity(self):
        g = self.game(hand=(CLOCKWORK, 'hand.enemy.add'),
            enemy_hand=tuple(f'card.{i}' for i in range(1, 11)))
        self.assertEqual(self.price(g, CLOCKWORK), 2)
        self.play(g, 'hand.enemy.add')
        self.assertEqual(self.price(g, CLOCKWORK), 2)
        self.assertEqual(len(g.state.players[2].hand), 10)
        self.assertTrue(any(event.kind == 'card_burned' for event in g.events))
        self.portable(g)

    def test_old_fact_keeps_original_inventories_after_real_hand_changes(self):
        g = self.game(hand=(MOUNTAIN, 'hand.draw', 'card.1'), deck=('card.2', 'card.3'))
        stage = self.fact(g).intrinsic
        validate_intrinsic_origin(stage, g.state, g.registry)
        self.play(g, 'hand.draw')
        self.assertEqual(self.price(g), 9)
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        with self.assertRaises(ValueError):
            validate_intrinsic_origin(stage, g.state, g.registry)

    def test_local_and_external_layers_follow_continuous_count_and_pay_once(self):
        g = self.game(hand=(MOUNTAIN, 'hand.local', 'hand.external', 'card.1'))
        self.play(g, 'hand.local')
        self.play(g, 'hand.external')
        f = self.fact(g)
        self.assertEqual((f.intrinsic.base_cost, f.intrinsic.amount, f.local_amount, f.amount), (12, 11, 8, 6))
        self.play(g, MOUNTAIN)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (6, 4))
        self.portable(g)

    def test_generated_initial_and_external_layers_and_minimum_keep_existing_order(self):
        g = self.game(hand=(MOUNTAIN, 'hand.external', 'card.1'))
        self.play(g, 'hand.external')
        f = capture_generated_quote_fact(g.state, g.registry, 1, MOUNTAIN, cost=CostSpec(delta=-3))
        self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (10, 7, 5))
        validate_generated_quote_fact(g.registry, f)
        floor = quote_generated_cost(g.state, g.registry, 1, MOUNTAIN, cost=CostSpec(set_to=0), minimum_cost=1)
        self.assertEqual(floor.amount, 1)

    def test_player_display_enumeration_validation_and_payment_share_original_hand_quote(self):
        g = self.game(hand=(MOUNTAIN, 'card.1', 'card.2'), mana=10)
        subject = self.source(g)
        g.validate(PlayCard(1, subject.id))
        port = g.for_player(1)
        dto = port.legal_actions()
        ref = g.observe(1)['players'][0]['hand'][0]['ref']
        action = next(action for action in dto['actions'] if action.get('card') == ref)
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['cost']['amount'], 10)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        play = g.state.play_history[-1]
        frozen = play.submitted_cost.quote.intrinsic.hand_cards
        self.assertEqual((play.cost, g.state.players[1].mana, frozen.quantity), (10, 0, 2))
        self.assertIn(subject.id, frozen.hands[0])
        self.assertNotIn(subject.id, g.state.players[1].hand)
        self.portable(g)

    def test_insufficient_mana_does_not_change_hand_or_payment(self):
        g = self.game(hand=(MOUNTAIN, 'card.1', 'card.2'), mana=9)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, MOUNTAIN)
        self.assertEqual(g.snapshot(), before)

    def test_printed_copy_silence_and_bounce_keep_rule_and_reacquire_current_price(self):
        g = self.game(hand=('hand.copy', 'hand.silence', 'hand.bounce', 'hand.bounce'), board=(MOUNTAIN,))
        self.play(g, 'hand.copy')
        self.play(g, 'hand.silence')
        self.play(g, 'hand.bounce')
        self.assertEqual(self.price(g), 11)
        self.play(g, 'hand.bounce')
        self.assertEqual(len(g.state.players[1].hand), 2)
        for eid in g.state.players[1].hand:
            subject = g.state.entities[eid]
            self.assertEqual(subject.base_cost, 12)
            self.assertEqual(g.registry.card(subject.card_id).hand_count_cost, HandCountCostSpec())
            self.assertEqual(quote_cost(g.state, g.registry, subject).amount, 11)
        self.portable(g)

    def test_card_played_wait_restores_and_keeps_paid_count_after_acquiring_another_card(self):
        g = self.game(hand=(MOUNTAIN, 'card.1', 'card.2'), board=('hand.watch',))
        subject_id = self.play(g, MOUNTAIN)
        receipt = g.state.play_history[-1].submitted_cost
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((receipt.quote.amount, receipt.quote.intrinsic.hand_cards.quantity), (10, 2))
        self.portable(g)
        self.choose(g)
        self.assertEqual(g.state.play_history[-1].submitted_cost, receipt)
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[subject_id]).amount, 9)
        self.assertEqual(g.state.players[1].mana, 0)
        self.assertIsNotNone(g.state.play_history[-1].paid_hand_close)
        self.portable(g)

    def test_delayed_failure_restores_paid_receipt_private_hands_ids_and_rng(self):
        g = self.game(hand=(MOUNTAIN, 'card.1', 'card.2'), board=('hand.watch',))
        self.play(g, MOUNTAIN)
        before = self.portable(g)
        visible = g.observe(1)
        with self.assertRaisesRegex(ResolutionError, 'unknown.hand.count'):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.observe(1), visible)
        self.portable(g)

    def test_count_fact_rejects_duplicate_future_boolean_unknown_scope_and_wrong_quantity(self):
        g = self.game(hand=(MOUNTAIN, 'card.1'), enemy_hand=('card.2',))
        f = self.fact(g).intrinsic.hand_cards
        for changes in ({'hands': (f.hands[0], f.hands[0])},
                {'hands': ((f.next_entity_id,), f.hands[1])}, {'hands': ((True,), f.hands[1])},
                {'hands': [f.hands[0], f.hands[1]]}, {'quantity': f.quantity + 1},
                {'subject_id': f.next_entity_id}, {'subject_id': f.hands[1][0]}, {'before': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(f, **changes)

    def test_physical_and_generated_quote_subjects_cannot_be_exchanged(self):
        g = self.game(hand=(MOUNTAIN, 'card.1'))
        physical = self.fact(g)
        changed = replace(physical.intrinsic.hand_cards, subject_id=g.state.players[1].hand[1])
        with self.assertRaisesRegex(ValueError, 'quoted subject'):
            replace(physical, intrinsic=replace(physical.intrinsic, hand_cards=changed))
        generated = capture_generated_quote_fact(g.state, g.registry, 1, MOUNTAIN)
        changed = replace(generated.intrinsic.hand_cards, subject_id=self.source(g).id, quantity=1, after=11)
        with self.assertRaisesRegex(ValueError, 'borrow a physical subject'):
            replace(generated, intrinsic=replace(generated.intrinsic, hand_cards=changed, amount=11))

    def test_submitted_receipt_requires_subject_in_original_hand_even_if_count_stays_equal(self):
        g = self.game(hand=(MOUNTAIN, 'card.1', 'card.2'))
        self.play(g, MOUNTAIN)
        receipt = g.state.play_history[-1].submitted_cost
        stage = receipt.quote.intrinsic
        hand = stage.hand_cards
        missing = replace(hand, hands=(hand.hands[0][1:], hand.hands[1]))
        self.assertEqual(missing.quantity, hand.quantity)
        with self.assertRaisesRegex(ValueError, 'original hand resident'):
            replace(receipt, quote=replace(receipt.quote, intrinsic=replace(stage, hand_cards=missing)))

    def test_friendly_zero_quote_still_rejects_unknown_unselected_hand_content(self):
        g = self.game(hand=(LOW, 'card.1', 'card.2'), enemy_hand=('card.3',))
        self.assertEqual(self.price(g, LOW), 0)
        state = g.state
        state.entities[state.players[2].hand[0]].card_id = 'unknown.hand.count'
        with self.assertRaisesRegex(ValueError, 'unknown.hand.count'):
            capture_quote_fact(state, g.registry, capture_cost_input(self.source(g, LOW)))

    def test_rehashed_snapshots_reject_missing_rewritten_or_extra_hand_count_operands(self):
        g = self.game(hand=(MOUNTAIN, 'card.1', 'card.2'), enemy_hand=('card.3',))
        self.play(g, MOUNTAIN)
        saved = self.portable(g)
        for edit in ('quantity', 'missing_field', 'missing_fact', 'extra', 'duplicate', 'future', 'missing_subject'):
            bad = deepcopy(saved)
            intrinsic = bad['state']['play_history'][0]['submitted_cost']['quote']['intrinsic']
            hand = intrinsic['hand_cards']
            if edit == 'quantity': hand['quantity'] += 1
            elif edit == 'missing_field': del intrinsic['hand_cards']
            elif edit == 'missing_fact': intrinsic['hand_cards'] = None
            elif edit == 'extra': hand['invented'] = 1
            elif edit == 'duplicate': hand['hands'][1] = deepcopy(hand['hands'][0])
            elif edit == 'future': hand['hands'][1] = [hand['next_entity_id']]
            else: hand['hands'][0] = hand['hands'][0][1:]
            with self.subTest(edit=edit), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad), registry())

    def test_player_prices_depend_on_public_opponent_count_without_private_identities(self):
        g = self.game(hand=(CLOCKWORK,), enemy_hand=(MOUNTAIN, 'coin', 'hand.weapon'))
        twin = self.game(hand=(CLOCKWORK,), enemy_hand=('card.1', 'card.2', 'card.3'))
        own = g.observe(1)
        self.assertEqual(own['players'][0]['hand'][0]['cost']['amount'], 9)
        self.assertEqual(twin.observe(1)['players'][0]['hand'][0]['cost'], own['players'][0]['hand'][0]['cost'])
        self.assertTrue(all(row['card_id'] is None and row.get('cost') is None for row in own['players'][1]['hand']))
        for secret in ('hand_cards', 'subject_id', 'next_entity_id', 'payment_state'):
            self.assertNotIn(secret, json.dumps(own))

    def test_default_none_and_strict_current_wire_keep_public_protocols(self):
        g = self.game(hand=('card.1',))
        self.assertIsNone(self.fact(g, 'card.1').intrinsic.hand_cards)
        self.play(g, 'card.1')
        saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        self.assertEqual((g.observe(1)['version'], g.for_player(1).observe()['version']),
            ('player-view-v115', 'player-actions-v13'))
        for version in (1, 170, 171, 217, True, '172'):
            bad = deepcopy(saved)
            bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(SnapshotError, f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
                Game.from_snapshot(bad, registry())


if __name__ == '__main__':
    unittest.main()
