"""Real Beast summon pricing through the original success, quote and payment paths."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, PlayerSetup, PlayerSummonCountCostSpec, PlayCard, Rarity, Registry,
    ResolutionError, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Summon, Transform)
from hs_sim.engine.intrinsic_costs import (validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import _intrinsic_stage_from_dict
from hs_sim.targets import canonical_digest

NATIVE = 'AT_041'
PROFILE = 'cost.player-summoned-beast-count-v1'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/player-summon-beast-cost-basics.json'
PIN = 'ccdbd7bc266541cdad8d01ca3971c54bcf654094e78ed58484049a5331e28197'


def evidence():
    value = json.loads(SUPPORT.read_bytes())
    if canonical_digest(value) != PIN:
        raise ValueError('Successful Beast price full evidence changed')
    for row in value['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Successful Beast price raw row changed')
    return value['records'][0]['data']


def registry():
    r = Registry('successful-beast-price-basics-v1')
    raw = evidence()
    r.register_card(CardDefinition('hero', 'Fixture hero', CardType.HERO, health=30,
        metadata=CardMetadata(False, (CardClass.DRUID,), None)))
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'],
        metadata=CardMetadata(True, (CardClass.DRUID,), Rarity.RARE, tribes=()),
        player_summon_count_cost=PlayerSummonCountCostSpec(PROFILE)))
    for name, tribes in (('b.beast', ('BEAST',)), ('b.totem', ('TOTEM',)),
                        ('b.all', ('all',)), ('b.blank', ()), ('b.unknown', None)):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=3,
            metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)))
    first = lambda c: c.state.players[c.player_id].board[0]
    bodies = {
        'b.make': lambda c: (Summon(c.player_id, 'b.beast'),),
        'b.totem.make': lambda c: (Summon(c.player_id, 'b.totem'),),
        'b.enemy': lambda c: (Summon(3-c.player_id, 'b.beast'),),
        'b.seven': lambda c: tuple(Summon(c.player_id, 'b.beast') for _ in range(7)),
        'b.acquire': lambda c: (AddToHand(c.player_id, NATIVE),),
        'b.kill': lambda c: (Destroy(first(c), c.source_id),),
        'b.bounce': lambda c: (ReturnToHand(first(c)),),
        'b.shape': lambda c: (Transform(first(c), 'b.totem'),),
        'b.control': lambda c: (ChangeControl(first(c), 3-c.player_id),),
        'b.fail': lambda c: (Summon(c.player_id, 'b.beast'), AddToHand(c.player_id, 'absent.beast-price')),
    }
    for name, body in bodies.items():
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def pause(c):
        if c.state.entities[c.event.source_id].card_id != NATIVE:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('more', 'Another real success', (Summon(c.player_id, 'b.beast'), AddToHand(c.player_id, NATIVE))),
            ChoiceOption('fault', 'Rollback', (InvokeBehavior('b.fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior('b.pause', pause)
    for name, event in (('b.commit.watch', 'card_committed'), ('b.complete.watch', 'card_played')):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=3,
            metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=()),
            triggers=(TriggerSpec(event, 'b.pause'),)))
    r.register_behavior('b.late.fail', lambda c: (AddToHand(c.player_id, 'absent.beast-price'),)
        if c.state.entities[c.event.source_id].card_id == NATIVE else ())
    r.register_card(CardDefinition('b.fail.watch', 'Failure listener', CardType.MINION, health=3,
        metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=()),
        triggers=(TriggerSpec('card_played', 'b.late.fail'),)))
    return r


class PlayerBeastSummonCostTests(unittest.TestCase):
    def game(self, hand=(NATIVE,), *, board=(), enemy_board=(), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy_board, mana=10, max_mana=10)), seed=73), registry())

    def source(self, g, name=NATIVE, player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand if g.state.entities[e].card_id == name)

    def play(self, g, name=NATIVE):
        player = g.state.active_player
        source = self.source(g, name, player)
        g.apply(PlayCard(player, source.id))
        return source.id

    def fact(self, g, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, player=player)))

    def price(self, g, player=1):
        return self.fact(g, player).amount

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry()).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        return saved

    def test_real_native_face_and_two_finite_profiles(self):
        raw = evidence()
        self.assertEqual((raw['id'], raw['cost'], raw['attack'], raw['health']), (NATIVE, 7, 6, 6))
        self.assertEqual(registry().card(NATIVE).player_summon_count_cost.profile_id, PROFILE)
        self.assertEqual(PlayerSummonCountCostSpec().profile_id, 'cost.player-summoned-totem-count-v1')
        for invalid in ('cost.any-history-expression', 'cost.player-summoned-dragon-count-v1', True):
            with self.assertRaises(ValueError):
                PlayerSummonCountCostSpec(invalid)

    def test_beasts_reduce_price_and_other_rows_remain_in_original_prefix(self):
        g = self.game((NATIVE, 'b.totem.make', 'b.enemy', 'b.make'))
        for card in ('b.totem.make', 'b.enemy', 'b.make'):
            self.play(g, card)
        fact = self.fact(g).intrinsic.player_summons
        self.assertEqual((self.price(g), fact.quantity, fact.selected_ids), (6, 1, (3,)))
        self.assertEqual([row.player_id for row in fact.records], [1, 2, 1])
        self.assertEqual(len(fact.records), 3)
        self.check(g)

    def test_success_before_acquisition_and_after_actual_turns_still_counts(self):
        g = self.game(('b.make', 'b.acquire'))
        self.play(g, 'b.make')
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.play(g, 'b.acquire')
        self.assertEqual(self.price(g), 6)
        self.check(g)

    def test_initial_board_and_failed_full_board_attempt_are_not_successes(self):
        g = self.game((NATIVE, 'b.make'), board=('b.beast',) * 7)
        self.play(g, 'b.make')
        self.assertEqual(self.price(g), 7)
        self.assertEqual(g.state.successful_summon_history, [])
        self.check(g)

    def test_normal_hand_beast_entry_and_reentry_each_count_once(self):
        g = self.game((NATIVE, 'b.beast', 'b.bounce'))
        source = self.play(g, 'b.beast')
        self.play(g, 'b.bounce')
        self.assertEqual(self.play(g, 'b.beast'), source)
        fact = self.fact(g).intrinsic.player_summons
        self.assertEqual((self.price(g), fact.quantity), (5, 2))
        self.assertEqual([row.entity_id for row in fact.records], [source, source])
        self.assertNotEqual(fact.records[0].minion.zone_epoch, fact.records[1].minion.zone_epoch)
        self.check(g)

    def test_death_and_later_transformation_do_not_reclassify_success(self):
        g = self.game((NATIVE, 'b.make', 'b.shape', 'b.kill'))
        self.play(g, 'b.make'); self.play(g, 'b.shape'); self.play(g, 'b.kill')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_summons.quantity), (6, 1))
        self.check(g)

    def test_control_transfer_preserves_original_summoning_player(self):
        g = self.game((NATIVE, 'b.make', 'b.control'), enemy_hand=(NATIVE,))
        self.play(g, 'b.make'); self.play(g, 'b.control')
        self.assertEqual((self.price(g), self.price(g, 2)), (6, 7))
        self.check(g)

    def test_all_tribes_contributes_only_one_success(self):
        g = self.game((NATIVE, 'b.all'))
        self.play(g, 'b.all')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_summons.quantity), (6, 1))
        self.check(g)

    def test_floor_zero_retains_full_success_quantity_and_native_is_not_a_beast(self):
        g = self.game((NATIVE, 'b.seven', 'b.kill', 'b.make', 'b.kill'))
        self.play(g, 'b.seven'); self.play(g, 'b.kill'); self.play(g, 'b.make')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_summons.quantity), (0, 8))
        self.play(g, 'b.kill'); self.play(g)
        record = g.state.play_history[-1]
        self.assertEqual(record.cost, 0)
        self.assertEqual(record.submitted_cost.quote.intrinsic.player_summons.quantity, 8)
        self.check(g)

    def test_unknown_payer_tribes_fail_even_after_a_matching_success(self):
        g = self.game((NATIVE, 'b.make', 'b.unknown'))
        self.play(g, 'b.make'); self.play(g, 'b.unknown')
        before = g.snapshot()
        with self.assertRaises(UnsupportedDefinitionError):
            self.price(g)
        self.assertEqual(g.snapshot(), before)

    def test_opponent_unknown_tribes_are_retained_without_entering_selection(self):
        g = self.game((NATIVE,), enemy_hand=('b.unknown',))
        g.apply(EndTurn(1)); self.play(g, 'b.unknown'); g.apply(EndTurn(2))
        fact = self.fact(g).intrinsic.player_summons
        self.assertEqual((self.price(g), fact.quantity), (7, 0))
        self.assertEqual(len(fact.records), 1)
        self.assertIsNone(fact.records[0].tribes)
        self.check(g)

    def waiting(self, watcher, completed):
        g = self.game((NATIVE, 'b.make'), board=(watcher,))
        self.play(g, 'b.make'); self.play(g)
        record = g.state.play_history[-1]
        original = record.submitted_cost.quote.intrinsic
        self.assertEqual((record.cost, record.completed, original.player_summons.quantity), (6, completed, 1))
        saved = self.check(g)
        peers = (Game.from_snapshot(saved, registry()), g.clone(), replay(build_replay(g), registry()))
        choice = SelectChoice(1, g.state.pending_choice.id, ('more',))
        g.apply(choice)
        for peer in peers:
            peer.apply(choice)
            self.assertEqual(peer.snapshot(), g.snapshot())
        self.assertEqual((g.state.players[1].mana, g.state.play_history[-1].cost, self.price(g)), (4, 6, 5))
        validate_intrinsic_history_prefix(original, g.state, g.registry)
        self.assertEqual(original.player_summons.quantity, 1)
        self.check(g)

    def test_committed_wait_keeps_original_payment_and_future_quotes_see_new_success(self):
        self.waiting('b.commit.watch', False)

    def test_completed_wait_keeps_original_payment_and_resumes_exactly_once(self):
        self.waiting('b.complete.watch', True)

    def test_failed_choice_rolls_back_added_success_and_keeps_waiting_payment(self):
        g = self.game((NATIVE, 'b.make'), board=('b.complete.watch',))
        self.play(g, 'b.make'); self.play(g); saved = self.check(g)
        with self.assertRaises(ResolutionError):
            g.apply(SelectChoice(1, g.state.pending_choice.id, ('fault',)))
        self.assertEqual(g.snapshot(), saved)
        self.check(g)

    def test_failed_completed_listener_rolls_back_native_entry_payment_and_history(self):
        g = self.game((NATIVE, 'b.make'), board=('b.fail.watch',))
        self.play(g, 'b.make'); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.price(g), 6)
        self.check(g)

    def test_same_amount_profile_substitution_is_rejected_against_pinned_definition(self):
        g = self.game(); stage = self.fact(g).intrinsic
        changed = replace(stage.player_summons, spec=PlayerSummonCountCostSpec())
        with self.assertRaises(ValueError):
            validate_intrinsic_stage_fact(g.registry, replace(stage, player_summons=changed))
        self.assertEqual(changed.after, stage.player_summons.after)

    def test_original_window_rejects_shortened_nonmatching_tail(self):
        g = self.game((NATIVE, 'b.make', 'b.totem.make'))
        self.play(g, 'b.make'); self.play(g, 'b.totem.make')
        stage = self.fact(g).intrinsic
        shortened = replace(stage.player_summons, records=stage.player_summons.records[:1],
                            next_successful_summon_id=2)
        changed = replace(stage, player_summons=shortened)
        validate_intrinsic_stage_fact(g.registry, changed)
        self.assertEqual(changed.amount, stage.amount)
        with self.assertRaises(ValueError):
            validate_intrinsic_origin(changed, g.state, g.registry)

    def test_beast_fact_json_typed_frame_and_private_information_boundary(self):
        g = self.game((NATIVE, 'b.make')); self.play(g, 'b.make')
        before = g.snapshot(); stage = self.fact(g).intrinsic
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)), stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))), stage)
        self.assertEqual(self.price(g), 6); self.assertEqual(g.snapshot(), before)
        text = json.dumps(g.observe(1)) + json.dumps(g.observe(2))
        self.assertNotIn('successful_summon_history', text)
        self.assertNotIn('selected_ids', text)
        self.assertNotIn(PROFILE, text)
        self.check(g)


if __name__ == '__main__':
    unittest.main()
