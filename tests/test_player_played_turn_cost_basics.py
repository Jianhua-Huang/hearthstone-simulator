"""One current-turn personal play-count policy, using full Frostwolf evidence."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardClass, CardDefinition, CardType, CostSpec,
    EndTurn, Game, IllegalAction, InteractableSpec, PaymentType, PlayerPlayedClassCostSpec,
    PlayerSetup, PlayCard, Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError,
    TriggerSpec, UseHeroPower)
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, CopyMinion,
    Damage, GainArmor, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.intrinsic_costs import (validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
import test_player_played_class_cost_basics as original
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

CARD = 'AV_134'
POLICY = 'cost.player-played-card-count-turn-v1'
PATH = Path(__file__).resolve().parents[1] / 'data/support/player-played-turn-cost-basics.json'
PIN = '9abbe8fcf3ccb0410bd7a2920a90699737bf7e9c003c9b52afbb05d1b5d67c35'


def evidence():
    support = json.loads(PATH.read_bytes())
    if canonical_digest(support) != PIN:
        raise ValueError('Current-turn complete evidence changed')
    if len(support['records']) != 1:
        raise ValueError('Expected one necessary complete representative')
    row = support['records'][0]
    if canonical_digest(row['data']) != row['data_sha256'] or row['id'] != CARD:
        raise ValueError('Current-turn original card evidence changed')
    return row['data']


def registry():
    r = original.registry()
    raw = evidence()
    r.register_card(CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], metadata=metadata(rarity=Rarity.RARE),
        player_played_class_cost=PlayerPlayedClassCostSpec(card_class=None, profile_id=POLICY)))

    def held(c):
        return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == CARD)

    def first(c):
        return next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == CARD)

    scripts = {
        'turn.acquire': lambda c: (AddToHand(c.player_id, CARD),),
        'turn.bounce': lambda c: (ReturnToHand(first(c)),),
        'turn.copy': lambda c: (CopyMinion(first(c), c.player_id, mode='base'),),
        'turn.silence': lambda c: (Silence(first(c)),),
        'turn.layers': lambda c: (ModifyCost(held(c), CostSpec(delta=-1)),
            AddCostModifier(c.player_id, CostSpec(delta=2, card_ids=(CARD,)))),
        'turn.lethal': lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 30, c.source_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))
    r.register_card(CardDefinition('turn.bare', 'Known original without class metadata', CardType.SPELL,
        on_play='class.noop'))

    def paid_wait(c):
        if c.state.entities[c.event.source_id].card_id != CARD:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Finish original paid play', (AddToHand(c.player_id, CARD),)),
            ChoiceOption('fault', 'Fail after suspension', (InvokeBehavior('class.fail', c.source_id, c.player_id),)),
        ), c.source_id),)

    r.register_behavior('turn.paid.wait', paid_wait)
    r.register_card(CardDefinition('turn.watch', 'Original paid play observer', CardType.MINION, health=3,
        triggers=(TriggerSpec('card_played', 'turn.paid.wait'),), metadata=metadata()))
    r.register_behavior('turn.observe', lambda c: (GainArmor(c.state.players[c.player_id].hero_id,
        len(original.played_cards(c.state, c.player_id, turn=c.state.turn))),))
    r.register_card(CardDefinition('turn.observe', 'Current original commitment observer', CardType.MINION,
        health=3, triggers=(TriggerSpec('card_committed', 'turn.observe'),), metadata=metadata()))
    return r


class PlayerPlayedTurnCostTests(unittest.TestCase):
    def game(self, hand=(CARD,), *, enemy_hand=(), board=(), enemy_board=(), mana=10, power=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=('card.1',)*3,
                        mana=mana, max_mana=10, hero_power_card_id=power),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',)*3,
                        mana=10, max_mana=10)), seed=22), registry())

    def source(self, g, cid=CARD, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand
                    if g.state.entities[eid].card_id == cid)

    def fact(self, g, player=1, cid=CARD):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))

    def price(self, g, player=1):
        return self.fact(g, player).amount

    def play(self, g, cid):
        eid = self.source(g, cid, g.state.active_player).id
        g.apply(PlayCard(g.state.active_player, eid))
        return eid

    def choose(self, g, option='continue'):
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
        return restored

    def one(self, *, extras=(), board=(), enemy_board=()):
        g = self.game((CARD, 'pal.free', *extras), board=board, enemy_board=enemy_board)
        self.play(g, 'pal.free')
        return g

    def test_complete_raw_native_ordinary_minion_and_pin(self):
        raw, card = evidence(), registry().card(CARD)
        self.assertEqual((raw['id'], raw['dbf_id'], raw['cost'], raw['attack'], raw['health']),
                         (CARD, 70238, 4, 3, 3))
        self.assertEqual(raw['text_en'], "Costs (1) less for each card you've played this turn.")
        self.assertEqual((raw['tags']['CLASS'], raw['tags']['RARITY']), (12, 3))
        self.assertEqual((card.cost, card.attack, card.health, card.metadata.classes, card.metadata.rarity),
                         (4, 3, 3, (CardClass.NEUTRAL,), Rarity.RARE))
        self.assertEqual((card.on_play, card.keywords), (None, ()))
        self.assertEqual(registry().card(original.LIGHT).metadata.tribes, ('elemental',))

    def test_two_finite_specs_reject_class_time_combinations_and_bad_types(self):
        self.assertEqual(PlayerPlayedClassCostSpec().card_class, CardClass.PALADIN)
        self.assertIsNone(PlayerPlayedClassCostSpec(card_class=None, profile_id=POLICY).card_class)
        for args in (dict(card_class=None), dict(card_class=True, profile_id=POLICY),
                     dict(card_class=CardClass.NEUTRAL, profile_id=POLICY),
                     dict(card_class=CardClass.PALADIN, profile_id=POLICY), dict(profile_id=POLICY),
                     dict(card_class=None, profile_id=True), dict(card_class=None, profile_id='unknown')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                PlayerPlayedClassCostSpec(**args)
        card = registry().card(CARD)
        for changes in (dict(kind=CardType.SPELL), dict(choice_only=True),
                        dict(interactable=InteractableSpec('class.noop')),
                        dict(board_minion_cost=BoardMinionCostSpec())):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                registry().register_card(replace(card, id='turn.invalid', **changes))

    def test_empty_history_is_zero_and_no_price_mutation(self):
        g = self.game()
        before = g.snapshot()
        f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((f.rows, f.selected_ids, f.quantity, f.before, f.after), ((), (), 0, 4, 4))
        self.assertEqual(self.source(g).base_cost, 4)
        self.assertEqual(g.snapshot(), before)

    def test_neutral_other_class_and_dual_class_each_count_one_play(self):
        g = self.game((CARD, 'pal.free', 'coin', 'mage.free', 'class.dual'))
        for cid in ('pal.free', 'coin', 'mage.free', 'class.dual'):
            self.play(g, cid)
        f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((f.selected_ids, f.quantity, self.price(g)), ((1, 2, 3, 4), 4, 0))

    def test_all_original_hand_card_types_count_without_class_filter(self):
        g = self.game((CARD, 'pal.free', 'pal.minion', 'pal.weapon', 'pal.location', 'pal.hero'))
        for cid in ('pal.free', 'pal.minion', 'pal.weapon', 'pal.location', 'pal.hero'):
            self.play(g, cid)
        self.assertEqual(self.fact(g).intrinsic.player_played_class.selected_ids, (1, 2, 3, 4, 5))
        self.assertEqual(self.price(g), 0)
        self.portable(g)

    def test_same_physical_return_and_replay_counts_each_root(self):
        g = self.game((CARD, 'pal.minion', 'class.return.pal'))
        first = self.play(g, 'pal.minion')
        self.play(g, 'class.return.pal')
        self.assertEqual(self.play(g, 'pal.minion'), first)
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_played_class.selected_ids), (1, (1, 2, 3)))

    def test_same_face_separate_physical_plays_each_count(self):
        g = self.one(extras=('pal.free',))
        self.play(g, 'pal.free')
        f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((f.quantity, self.price(g)), (2, 2))
        self.assertNotEqual(f.rows[0].face.source_id, f.rows[1].face.source_id)

    def test_acquisition_later_uses_all_earlier_current_turn_plays(self):
        g = self.game(('pal.free', 'turn.acquire'))
        self.play(g, 'pal.free')
        self.play(g, 'turn.acquire')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_played_class.selected_ids), (2, (1, 2)))

    def test_actual_global_turn_resets_both_payers_and_old_class_policy_stays(self):
        g = self.game((CARD, original.LIGHT, 'pal.free', 'coin'),
                      enemy_hand=(CARD, 'pal.free'))
        self.play(g, 'pal.free')
        self.play(g, 'coin')
        self.assertEqual((self.price(g), self.price(g, 2), self.fact(g, cid=original.LIGHT).amount), (2, 4, 8))
        g.apply(EndTurn(1))
        self.assertEqual((self.price(g), self.price(g, 2)), (4, 4))
        self.play(g, 'pal.free')
        self.assertEqual((self.price(g), self.price(g, 2)), (4, 3))
        g.apply(EndTurn(2))
        f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((self.price(g), self.price(g, 2), len(f.rows), f.selected_ids), (4, 4, 3, ()))
        self.assertEqual(self.fact(g, cid=original.LIGHT).amount, 8)
        self.portable(g)

    def test_known_original_without_class_metadata_needs_no_invented_class(self):
        g = self.game((CARD, 'turn.bare'))
        self.play(g, 'turn.bare')
        f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((f.quantity, self.price(g)), (1, 3))
        self.assertIsNone(f.rows[0].face.metadata)
        self.portable(g)

    def test_automatic_cast_summon_and_skill_do_not_create_paid_hand_roots(self):
        g = self.game((CARD, 'class.auto', 'class.summon'), power='mage.power')
        self.play(g, 'class.auto')
        self.play(g, 'class.summon')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual((self.price(g), len(g.state.play_history), len(g.state.cast_history)), (2, 2, 3))

    def test_countered_paid_root_counts_once(self):
        g = self.game((CARD, 'pal.two'), enemy_board=('class.counter',))
        self.play(g, 'pal.two')
        self.assertTrue(g.state.play_history[0].countered)
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_played_class.selected_ids), (3, (1,)))
        self.play(g, CARD)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (3, 5))
        self.portable(g)

    def test_committed_waiting_root_is_visible_before_completion(self):
        g = self.game((CARD, 'pal.wait'), board=('turn.observe',))
        self.play(g, 'pal.wait')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.play_history[0].completed)
        self.assertEqual((self.price(g), g.state.entities[g.state.players[1].hero_id].armor), (3, 1))
        restored = self.portable(g)
        self.choose(restored)
        self.choose(g)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(self.price(g), 3)

    def test_health_payment_and_zero_cost_cards_are_still_original_plays(self):
        g = self.game((CARD, 'class.health', 'pal.two'))
        self.play(g, 'class.health')
        self.play(g, 'pal.two')
        self.assertEqual((self.price(g), g.state.players[1].mana,
                          g.state.entities[g.state.players[1].hero_id].health), (2, 10, 28))

    def test_zero_floor_does_not_cap_quantity_or_repeat_payment(self):
        g = self.game((CARD, *('pal.free',)*5))
        for _ in range(5):
            self.play(g, 'pal.free')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_played_class.quantity), (0, 5))
        self.play(g, CARD)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (0, 10))

    def test_self_is_excluded_from_own_payment_then_counts_for_next_source(self):
        g = self.game((CARD, CARD))
        self.play(g, CARD)
        paid = g.state.play_history[0].submitted_cost.quote.intrinsic.player_played_class
        self.assertEqual((paid.quantity, paid.rows, g.state.play_history[0].cost, self.price(g)), (0, (), 4, 3))

    def test_current_transformed_face_does_not_rewrite_original_count(self):
        g = self.game((CARD, 'pal.minion', 'class.transform'))
        eid = self.play(g, 'pal.minion')
        self.play(g, 'class.transform')
        f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((g.state.entities[eid].card_id, f.rows[0].face.card_id, f.quantity, self.price(g)),
                         ('card.1', 'pal.minion', 2, 2))
        self.portable(g)

    def test_printed_copy_silence_bounce_and_next_turn_requery_current_history(self):
        g = self.game((CARD, 'turn.copy', 'turn.silence', 'turn.bounce'))
        eid = self.play(g, CARD)
        for cid in ('turn.copy', 'turn.silence', 'turn.bounce'):
            self.play(g, cid)
        self.assertEqual((self.source(g).id, self.price(g), self.source(g).base_cost), (eid, 0, 4))
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertEqual(self.price(g), 4)
        self.portable(g)

    def test_physical_generated_player_quotes_and_current_turn_query_are_pure(self):
        g = self.one()
        saved = g.snapshot()
        physical = self.fact(g)
        generated = capture_generated_quote_fact(g.state, g.registry, 1, CARD)
        self.assertEqual((physical.amount, generated.amount), (3, 3))
        self.assertEqual(physical.intrinsic, generated.intrinsic)
        self.assertEqual([p.id for p in original.played_cards(g.state, 1, turn=g.state.turn)], [1])
        card = next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id'] == CARD)
        self.assertEqual(card['cost']['amount'], 3)
        self.assertEqual(g.snapshot(), saved)

    def test_local_external_layers_share_the_exact_current_turn_payment(self):
        g = self.one(extras=('turn.layers',))
        self.play(g, 'turn.layers')
        f = self.fact(g)
        self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (2, 1, 3))
        self.play(g, CARD)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (3, 7))
        self.portable(g)

    def test_player_legal_action_pays_exact_displayed_price(self):
        g = self.one()
        port = g.for_player(1)
        dto = port.legal_actions()
        card = next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id'] == CARD)
        action = next(a for a in dto['actions'] if a.get('card') == card['ref'])
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (3, 7))

    def test_failed_and_insufficient_actions_roll_back_original_prefix(self):
        g = self.game((CARD, 'class.fail'), mana=1)
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, CARD)
        self.assertEqual(g.snapshot(), saved)
        with self.assertRaises(ResolutionError):
            self.play(g, 'class.fail')
        self.assertEqual(g.snapshot(), saved)

    def test_paid_waiting_dictionary_and_typed_frames_restore_and_resume(self):
        g = self.one(board=('turn.watch',))
        self.play(g, CARD)
        self.assertIsNotNone(g.state.pending_choice)
        saved = g.snapshot()
        wire = saved['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['player_played_class']
        self.assertEqual(wire['spec'], {'card_class': None, 'profile_id': POLICY})
        self.assertEqual((wire['turn'], wire['quantity'], wire['after']), (1, 1, 3))
        restored = self.portable(g)
        self.choose(restored)
        self.choose(g)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana, self.price(g)), (3, 7, 2))

    def test_old_paid_amount_keeps_original_turn_after_real_handoff(self):
        g = self.one(board=('turn.watch',))
        self.play(g, CARD)
        stage = g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.choose(g)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertEqual((self.price(g), stage.player_played_class.turn,
                          stage.player_played_class.quantity, g.state.play_history[1].cost), (4, 1, 1, 3))
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        with self.assertRaises(ValueError):
            validate_intrinsic_origin(stage, g.state, g.registry)
        self.portable(g)

    def test_exception_after_paid_choice_rolls_back_to_that_choice_boundary(self):
        g = self.one(board=('turn.watch',))
        self.play(g, CARD)
        self.portable(g)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), saved)

    def test_complete_old_and_opponent_rows_remain_when_current_quantity_zero(self):
        g = self.game((CARD, 'pal.free'), enemy_hand=('pal.free',))
        self.play(g, 'pal.free')
        g.apply(EndTurn(1))
        self.play(g, 'pal.free')
        g.apply(EndTurn(2))
        f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((len(f.rows), [r.turn for r in f.rows], f.selected_ids, f.quantity), (2, [1, 2], (), 0))
        self.portable(g)

    def test_frozen_rows_and_exact_selection_window_reject_forged_numbers(self):
        g = self.one()
        stage = self.fact(g).intrinsic
        f = stage.player_played_class
        with self.assertRaises(FrozenInstanceError):
            f.rows[0].turn = 2
        for changes in (dict(quantity=True), dict(selected_ids=(True,)), dict(selected_ids=()), dict(rows=()),
                        dict(rows=list(f.rows)), dict(play_history_length=2), dict(turn=2),
                        dict(action=f.action+1), dict(next_entity_id=f.rows[0].face.source_id)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(stage, player_played_class=replace(f, **changes))

    def test_non_selected_original_face_is_still_pinned_even_with_zero_quantity(self):
        g = self.one()
        g.apply(EndTurn(1))
        f = self.fact(g).intrinsic.player_played_class
        row = replace(f.rows[0], face=replace(f.rows[0].face, metadata=metadata(collectible=False)))
        stage = replace(self.fact(g).intrinsic, player_played_class=replace(f, rows=(row,)))
        self.assertEqual(stage.player_played_class.quantity, 0)
        with self.assertRaises(ValueError):
            validate_intrinsic_stage_fact(g.registry, stage)
        with self.assertRaises(ValueError):
            validate_intrinsic_history_prefix(stage, g.state, g.registry)

    def test_rehashed_paid_wire_rejects_policy_class_prefix_clock_and_identity_rewrites(self):
        g = self.one()
        self.play(g, CARD)
        saved = g.snapshot()
        for mode in ('leaf', 'extra', 'rows', 'selected', 'quantity', 'class', 'old-policy', 'profile',
                     'source', 'owner', 'metadata', 'row-turn', 'turn', 'action', 'bool'):
            bad = deepcopy(saved)
            stage = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            f = stage['player_played_class']
            if mode == 'leaf': del stage['player_played_class']
            elif mode == 'extra': f['invented'] = 1
            elif mode == 'rows': f['rows'] = []
            elif mode == 'selected': f['selected_ids'] = []
            elif mode == 'quantity': f['quantity'] = 2
            elif mode == 'class': f['spec']['card_class'] = 'PALADIN'
            elif mode == 'old-policy':
                f['spec'] = {'card_class': 'PALADIN', 'profile_id': 'cost.player-played-class-v1'}
            elif mode == 'profile': f['spec']['profile_id'] = 'unknown'
            elif mode == 'source': f['rows'][0]['face']['source_id'] += 1
            elif mode == 'owner': f['rows'][0]['face']['owner_turn_id'] += 1
            elif mode == 'metadata': f['rows'][0]['face']['metadata']['collectible'] = False
            elif mode == 'row-turn': f['rows'][0]['turn'] += 1
            elif mode == 'turn': f['turn'] += 1
            elif mode == 'action': f['rows'][0]['action'] += 1
            else: f['rows'][0]['face']['player_id'] = True
            with self.subTest(mode=mode), self.assertRaises(SnapshotError):
                Game.from_snapshot(original.rehash(bad), registry())

    def test_player_views_hide_full_prefix_and_opponent_cards(self):
        g = self.game((CARD, 'pal.free'), enemy_hand=('mage.free',))
        self.play(g, 'pal.free')
        for player in (1, 2):
            text = json.dumps(g.for_player(player).observe())
            for internal in ('player_played_class', 'selected_ids', 'submitted_cost', 'payment_state', 'hand_entry_id'):
                self.assertNotIn(internal, text)
        self.assertNotIn(CARD, json.dumps(g.observe(2)))
        self.assertNotIn('mage.free', json.dumps(g.observe(1)))
        self.portable(g)

    def test_same_layout_new_semantics_and_explicit_null_default_leaf(self):
        g = self.game(('card.1',))
        self.assertIsNone(self.fact(g, cid='card.1').intrinsic.player_played_class)
        self.play(g, 'card.1')
        saved = g.snapshot()
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']),
                         ('prototype-v302', CORE_EFFECTS_VERSION, 266))
        for mode in ('old-schema', 'future-schema', 'bool-schema', 'old-rules', 'old-effects'):
            bad = deepcopy(saved)
            if mode == 'old-schema': bad['schema_version'] = 207
            elif mode == 'future-schema': bad['schema_version'] = 217
            elif mode == 'bool-schema': bad['schema_version'] = True
            elif mode == 'old-rules': bad['ruleset']['id'] = 'prototype-v224'
            else: bad['mechanics_version']['version'] = 'core-effects-v218'
            with self.subTest(mode=mode), self.assertRaises(SnapshotError):
                Game.from_snapshot(original.rehash(bad), registry())
        self.portable(g)

    def test_accepted_terminal_root_is_not_erased_by_missing_completion(self):
        g = self.game((CARD, 'turn.lethal'))
        self.play(g, 'turn.lethal')
        self.assertEqual(g.state.status, 'finished')
        self.assertEqual((self.fact(g).intrinsic.player_played_class.selected_ids, self.price(g)), ((1,), 3))
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
