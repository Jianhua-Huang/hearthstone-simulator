"""Real all-game draw price, with original draw and payment continuations."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import asdict, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CastWhenDrawnSpec, CostSpec,
    EndTurn, Game, HeroHealthChangeCostSpec, IllegalAction, IntrinsicCostSpec, Keyword,
    MinionDeathCostSpec, PlayerDrawCountCostFact, PlayerDrawCountCostSpec, PlayerSetup,
    PlayCard, Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact, quote_cost
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage, Draw, GainArmor,
    InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact, validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.player_draw_count_costs import validate_definition, validate_prefix
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import _intrinsic_stage_from_dict, canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, DrawMatching, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry, setup
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

GIANT = 'TOY_530'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/player-draw-count-cost-basics.json'
PIN = 'e88ccefe756362fd54d825806c8ef92495dfa3e9663665bfa69d238914ac0ee3'


def evidence():
    value = json.loads(SUPPORT.read_text(encoding='utf-8'))
    if canonical_digest(value) != PIN:
        raise ValueError('Physical draw price evidence changed')
    row, = value['records']
    if row['id'] != GIANT or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Physical draw price complete raw changed')
    return row['data']


def registry():
    r = opening_registry()
    raw = evidence()
    r.register_card(CardDefinition(GIANT, raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        metadata=metadata(rarity=Rarity.EPIC, tribes=('MECH',)),
        player_draw_count_cost=PlayerDrawCountCostSpec()))

    def hand(c, cid=GIANT):
        return next(c.state.entities[eid] for eid in c.state.players[c.player_id].hand
            if c.state.entities[eid].card_id == cid)

    def top(c):
        return CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])

    def board(c):
        return next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == GIANT)

    def wait(c, after=()):
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue original draw', after),
            ChoiceOption('fault', 'Delayed rollback probe', (InvokeBehavior('d.fail', c.source_id, c.player_id),)),
        ), c.source_id),)

    bodies = {
        'd.one': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'd.two': lambda c: (Draw(c.player_id, 2, c.source_id),),
        'd.twenty': lambda c: (Draw(c.player_id, 20, c.source_id),),
        'd.twentysix': lambda c: (Draw(c.player_id, 26, c.source_id),),
        'd.enemy': lambda c: (Draw(3-c.player_id, 2, c.source_id),),
        'd.acquire': lambda c: (AddToHand(c.player_id, GIANT),),
        'd.move': lambda c: (MoveCard(top(c), c.player_id, Zone.HAND),),
        'd.copy': lambda c: (CopyCard(top(c), c.player_id),),
        'd.create': lambda c: (AddToHand(c.player_id, 'card.1'),),
        'd.redeck': lambda c: (MoveCard(CardReference.capture(hand(c, 'card.1')), c.player_id, Zone.DECK, 'top'),),
        'd.copy.enemy': lambda c: (CopyCard(CardReference.capture(hand(c)), 3-c.player_id, mode='base'),),
        'd.local': lambda c: (ModifyCost(hand(c).id, CostSpec(set_to=4)),),
        'd.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-1, card_ids=(GIANT,))),),
        'd.silence': lambda c: (Silence(board(c)),),
        'd.bounce': lambda c: (ReturnToHand(board(c)),),
        'd.fail': lambda c: (Draw(c.player_id, source_id=c.source_id), AddToHand(c.player_id, 'unknown.draw.price')),
        'd.skip': lambda c: (DrawMatching(c.player_id, query=PoolQuery(), empty_deck='skip'),),
        'd.auto': lambda c: (GainArmor(c.player_id, 2),),
        'd.auto.pause': lambda c: wait(c),
        'd.auto.end': lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 50, c.source_id),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        automatic = cid.startswith('d.auto')
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            keywords=(Keyword.CASTS_WHEN_DRAWN,) if automatic else (),
            cast_when_drawn=CastWhenDrawnSpec(choices='player') if automatic else None))
    r.register_behavior('d.first.wait', lambda c: wait(c)
        if c.event.player_id == c.player_id and len(c.state.draw_history) == 1 else ())
    r.register_card(CardDefinition('d.draw.watch', 'Original first draw window', CardType.MINION,
        health=5, triggers=(TriggerSpec('card_drawn', 'd.first.wait'),)))
    r.register_behavior('d.paid.wait', lambda c: wait(c, (Draw(c.player_id, source_id=c.source_id),))
        if c.state.entities[c.event.source_id].card_id == GIANT else ())
    r.register_card(CardDefinition('d.paid.watch', 'Original completed payment window', CardType.MINION,
        health=5, triggers=(TriggerSpec('card_played', 'd.paid.wait'),)))
    r.register_behavior('d.draw.fail', lambda c: (AddToHand(c.player_id, 'unknown.draw.price'),))
    r.register_card(CardDefinition('d.fail.watch', 'Original draw rollback probe', CardType.MINION,
        health=5, triggers=(TriggerSpec('card_drawn', 'd.draw.fail'),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class PlayerDrawCountCostTests(unittest.TestCase):
    def game(self, hand=(GIANT,), *, deck=('card.1',)*30, board=(), enemy_hand=(), enemy_deck=('card.2',)*5):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, deck=deck, board=board, mana=10, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, deck=enemy_deck, mana=10, max_mana=10)), seed=41), registry())

    def source(self, g, cid=GIANT, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)

    def play(self, g, cid=GIANT):
        player = g.state.active_player
        g.apply(PlayCard(player, self.source(g, cid, player).id))

    def choose(self, g, option='continue'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def fact(self, g, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, player=player)))

    def price(self, g, player=1):
        return self.fact(g, player).amount

    def one(self, extras=(), *, board=(), deck=('card.1',)*30):
        g = self.game((GIANT, 'd.one', *extras), board=board, deck=deck)
        self.play(g, 'd.one')
        return g

    def twenty(self, extras=(), *, board=()):
        g = self.game((GIANT, 'd.twenty', *extras), board=board)
        self.play(g, 'd.twenty')
        return g

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry()).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for player in (1, 2):
            self.assertEqual(Game.from_snapshot(saved, registry()).observe(player), g.observe(player))
        return saved

    def typed(self, g, stage):
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)), stage)
        wire = json.loads(json.dumps(asdict(stage)))
        self.assertEqual(_intrinsic_stage_from_dict(wire), stage)

    def test_complete_native_raw_pin_twentyfive_eight_eight_epic_mech_has_only_price(self):
        raw = evidence()
        rows = json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes())
        self.assertEqual(raw, next(row for row in rows if row['id'] == GIANT))
        d = registry().card(GIANT)
        self.assertEqual((d.cost, d.attack, d.health, d.metadata.classes, d.metadata.tribes, d.metadata.rarity),
            (25, 8, 8, (CardClass.NEUTRAL,), ('MECH',), Rarity.EPIC))
        self.assertIsNone(d.on_play)
        self.assertIsNone(d.battlecry)
        self.assertEqual(d.player_draw_count_cost, PlayerDrawCountCostSpec())

    def test_finite_profile_ordinary_type_and_no_extra_quantity_formulas(self):
        for profile in (None, True, 'cost.drawn-this-turn', 'arbitrary.formula'):
            with self.subTest(profile=profile), self.assertRaises(ValueError): PlayerDrawCountCostSpec(profile)
        d = registry().card(GIANT)
        for change in (dict(kind=CardType.WEAPON, durability=1), dict(choice_only=True), dict(player_draw_count_cost='expression'),
                dict(minion_death_cost=MinionDeathCostSpec()), dict(hero_health_change_cost=HeroHealthChangeCostSpec()),
                dict(intrinsic_costs=(IntrinsicCostSpec(delta=-1),))):
            with self.subTest(change=change), self.assertRaises(ValueError): validate_definition(replace(d, **change))

    def test_empty_actual_history_keeps_printed_price_and_explicit_empty_fact(self):
        g = self.game()
        f = self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g), f.records, f.selected_ids, f.quantity, f.draw_history_length), (25, (), (), 0, 0))
        with self.assertRaises(FrozenInstanceError): f.quantity = 1
        self.portable(g)

    def test_two_real_cards_of_same_face_are_two_draws_and_do_not_mutate_base(self):
        g = self.game((GIANT, 'd.two'))
        self.play(g, 'd.two')
        f = self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g), f.quantity, f.selected_ids), (23, 2, (1, 2)))
        self.assertEqual(self.source(g).base_cost, 25)
        self.assertNotEqual(f.records[0].entity_id, f.records[1].entity_id)
        self.portable(g)

    def test_actual_draws_before_native_acquisition_are_counted(self):
        g = self.game(('d.two', 'd.acquire'))
        self.play(g, 'd.two')
        self.play(g, 'd.acquire')
        self.assertEqual(self.price(g), 23)
        self.assertEqual(len(g.state.hand_entries), 5)
        self.portable(g)

    def test_opponent_draws_stay_in_complete_prefix_without_own_discount(self):
        g = self.one(('d.enemy',), deck=('card.1',)*4)
        self.play(g, 'd.enemy')
        f = self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g), len(f.records), f.selected_ids, f.quantity), (24, 3, (1,), 1))
        self.portable(g)

    def test_fatigue_attempts_are_saved_but_are_not_physical_cards_drawn(self):
        # Use the original one-card body three times without a lethal fatigue run.
        g = self.game((GIANT, 'd.one', 'd.one', 'd.one'), deck=('card.1',))
        for _ in range(3): self.play(g, 'd.one')
        f = self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g), f.quantity, tuple(row.outcome for row in f.records)), (24, 1, ('hand', 'fatigue', 'fatigue')))
        self.portable(g)

    def test_ordinary_move_copy_generation_and_initial_hand_are_not_draws(self):
        g = self.game((GIANT, 'd.move', 'd.copy', 'd.create'))
        for cid in ('d.move', 'd.copy', 'd.create'): self.play(g, cid)
        self.assertEqual((self.price(g), len(g.state.draw_history)), (25, 0))
        self.assertGreater(len(g.state.hand_entries), 4)
        self.portable(g)

    def test_empty_matching_skip_does_not_invent_a_draw_or_fatigue(self):
        g = self.game((GIANT, 'd.skip'), deck=())
        self.play(g, 'd.skip')
        self.assertEqual((self.price(g), g.state.draw_history, g.state.players[1].fatigue), (25, [], 0))
        self.portable(g)

    def test_burned_real_card_contributes_once_to_same_original_quantity(self):
        g = self.game((GIANT, 'd.two', *('card.1',)*8))
        self.play(g, 'd.two')
        f = self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g), f.quantity, tuple(row.outcome for row in f.records)), (23, 2, ('hand', 'burned')))
        self.portable(g)

    def test_original_cast_when_drawn_and_replacement_are_two_physical_draws(self):
        g = self.one(deck=('d.auto', 'card.1', 'card.2'))
        f = self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g), f.quantity, tuple(row.outcome for row in f.records)), (23, 2, ('cast', 'hand')))
        self.assertEqual(f.records[0].replacement_id, 2)
        self.typed(g, self.fact(g).intrinsic)
        self.portable(g)

    def test_draw_accepted_before_terminal_interruption_still_counts(self):
        g = self.one(deck=('d.auto.end', 'card.1'))
        self.assertNotEqual(g.state.status, 'playing')
        self.assertTrue(g.state.draw_history[0].interrupted)
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_draws.quantity), (24, 1))
        self.portable(g)

    def test_same_physical_card_drawn_again_contributes_a_second_occurrence(self):
        g = self.one(('d.redeck', 'd.one'))
        self.play(g, 'd.redeck')
        self.play(g, 'd.one')
        f = self.fact(g).intrinsic.player_draws
        self.assertEqual(f.records[0].entity_id, f.records[1].entity_id)
        self.assertEqual((self.price(g), f.quantity), (23, 2))
        self.portable(g)

    def test_all_game_quantity_persists_and_uses_original_player_on_turn_draws(self):
        g = self.one()
        old = self.fact(g).intrinsic
        g.apply(EndTurn(1)); self.assertEqual(self.price(g), 24)
        g.apply(EndTurn(2)); self.assertEqual(self.price(g), 23)
        self.assertEqual(self.fact(g).intrinsic.player_draws.selected_ids, (1, 3))
        validate_intrinsic_history_prefix(old, g.state, g.registry)
        self.portable(g)

    def test_physical_generated_player_quote_has_same_original_stage(self):
        g = self.one()
        actual = self.fact(g)
        generated = capture_generated_quote_fact(g.state, g.registry, 1, GIANT)
        self.assertEqual((actual.intrinsic, actual.amount), (generated.intrinsic, generated.amount))
        validate_generated_quote_fact(g.registry, generated)
        row = next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id'] == GIANT)
        self.assertEqual(row['cost']['amount'], 24)
        self.typed(g, actual.intrinsic)

    def test_twenty_real_draws_allow_native_five_mana_play_with_one_frozen_payment(self):
        g = self.twenty()
        self.assertEqual(self.price(g), 5)
        self.play(g)
        record = g.state.play_history[-1]
        self.assertEqual((record.cost, g.state.players[1].mana, record.submitted_cost.quote.intrinsic.player_draws.quantity), (5, 5, 20))
        giant = g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((giant.base_cost, giant.attack, giant.health), (25, 8, 8))
        self.portable(g)

    def test_more_draws_than_printed_price_floor_zero_and_generated_minimum_is_later(self):
        g = self.game((GIANT, 'd.twentysix'))
        self.play(g, 'd.twentysix')
        self.assertEqual(self.price(g), 0)
        generated = capture_generated_quote_fact(g.state, g.registry, 1, GIANT, minimum_cost=2)
        self.assertEqual((generated.intrinsic.amount, generated.amount), (0, 2))
        self.play(g)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (0, 10))
        self.portable(g)

    def test_original_local_then_external_layers_and_actual_payment_are_shared(self):
        g = self.one(('d.local', 'd.external'))
        self.play(g, 'd.local'); self.play(g, 'd.external')
        f = self.fact(g)
        self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (24, 4, 3))
        self.play(g)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (3, 7))
        self.portable(g)

    def test_insufficient_mana_rolls_back_without_playing_native_or_advancing_draws(self):
        g = self.one(); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_player_command_pays_visible_native_price_and_uses_original_board_entry(self):
        g = self.twenty(); port = g.for_player(1); dto = port.legal_actions()
        row = next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id'] == GIANT)
        action = next(a for a in dto['actions'] if a.get('card') == row['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'], 'action':action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (5, 5))
        self.portable(g)

    def test_ordinary_printed_copy_queries_new_payer_history(self):
        g = self.one(('d.copy.enemy',))
        self.play(g, 'd.copy.enemy')
        self.assertEqual((self.price(g), self.price(g, 2)), (24, 25))
        self.assertEqual(self.source(g, player=2).base_cost, 25)
        self.portable(g)

    def test_silence_and_normal_bounce_keep_printed_input_and_player_history(self):
        g = self.twenty(('d.silence', 'd.bounce'))
        self.play(g); self.play(g, 'd.silence'); self.play(g, 'd.bounce')
        self.assertEqual((self.source(g).base_cost, self.price(g), len(g.state.draw_history)), (25, 5, 20))
        self.portable(g)

    def test_first_ordinary_draw_choice_can_finish_without_rewriting_old_quote(self):
        g = self.game((GIANT, 'd.two'), board=('d.draw.watch',))
        self.play(g, 'd.two')
        old = self.fact(g).intrinsic
        self.assertEqual((old.amount, old.player_draws.records[0].phase), (24, 'drawing'))
        saved = self.portable(g); other = Game.from_snapshot(saved, registry()); self.typed(g, old)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.price(g), 23)
        validate_intrinsic_history_prefix(old, g.state, g.registry)
        self.portable(g)

    def test_pending_cast_can_add_real_cast_and_replacement_links_after_frozen_quote(self):
        g = self.game((GIANT, 'd.one'), deck=('d.auto', 'card.1'), board=('d.draw.watch',))
        self.play(g, 'd.one'); old = self.fact(g).intrinsic
        self.assertEqual((old.amount, old.player_draws.records[0].phase, old.player_draws.records[0].cast_id), (24, 'pending_cast', None))
        self.portable(g); self.typed(g, old); self.choose(g)
        self.assertEqual(self.price(g), 23)
        self.assertIsNotNone(g.state.draw_history[0].cast_id)
        validate_intrinsic_history_prefix(old, g.state, g.registry)
        self.portable(g)

    def test_casting_choice_finishes_original_phase_and_keeps_original_quantity(self):
        g = self.one(deck=('d.auto.pause', 'card.1'))
        old = self.fact(g).intrinsic
        self.assertEqual((old.amount, old.player_draws.records[0].phase), (24, 'casting'))
        saved = self.portable(g); other = Game.from_snapshot(saved, registry()); self.typed(g, old)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        validate_intrinsic_history_prefix(old, g.state, g.registry)
        self.assertEqual((old.player_draws.quantity, self.price(g)), (1, 23))
        self.portable(g)

    def test_paid_native_completed_choice_later_draw_keeps_accepted_five_mana(self):
        g = self.twenty(board=('d.paid.watch',)); self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        record = g.state.play_history[-1]; self.assertTrue(record.completed)
        old = record.submitted_cost.quote.intrinsic
        saved = self.portable(g); other = Game.from_snapshot(saved, registry())
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        fresh = capture_generated_quote_fact(g.state, g.registry, 1, GIANT)
        self.assertEqual((fresh.amount, g.state.play_history[-1].cost, g.state.players[1].mana), (4, 5, 5))
        validate_intrinsic_history_prefix(old, g.state, g.registry)
        self.portable(g)

    def test_delayed_draw_fault_restores_original_paid_choice_and_full_draw_prefix(self):
        g = self.twenty(board=('d.paid.watch',)); self.play(g); before = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)

    def test_draw_listener_fault_rolls_back_the_whole_root_and_new_count(self):
        g = self.game((GIANT, 'd.two'), board=('d.fail.watch',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'd.two')
        self.assertEqual(g.snapshot(), before)

    def test_complete_fact_rejects_fake_allocations_selection_boolean_and_equal_price_prefix_edits(self):
        g = self.one(('d.enemy',)); self.play(g, 'd.enemy')
        f = self.fact(g).intrinsic.player_draws
        for change in (dict(quantity=True), dict(selected_ids=(True,)), dict(draw_history_length=2),
                dict(next_entity_id=1), dict(turn=0), dict(cast_history_length=-1),
                dict(selected_ids=(1, 2)), dict(records=list(f.records)),
                dict(records=(replace(f.records[0], action=g.state.action_number+1), *f.records[1:]))):
            with self.subTest(change=change), self.assertRaises(ValueError): replace(f, **change)
        bad = replace(f, records=(f.records[0], replace(f.records[1], card_id='unknown.draw.price'), f.records[2]))
        stage = replace(self.fact(g).intrinsic, player_draws=bad)
        with self.assertRaises(ValueError): validate_intrinsic_stage_fact(g.registry, stage)

    def test_retained_history_rejects_reversed_phase_changed_identity_and_deleted_excluded_row(self):
        g = self.one(('d.enemy',)); self.play(g, 'd.enemy'); f = self.fact(g).intrinsic.player_draws
        for mode in ('phase', 'source', 'outcome', 'excluded'):
            bad = g.state
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                if mode == 'phase': bad.draw_history[0] = replace(bad.draw_history[0], phase='drawing')
                elif mode == 'source': bad.draw_history[0] = replace(bad.draw_history[0], source_id=None)
                elif mode == 'outcome': bad.draw_history[0] = replace(bad.draw_history[0], outcome='burned')
                else: bad.draw_history.pop()
                validate_prefix(f, bad, g.registry)

    def test_rehashed_native_payment_rejects_lost_none_wrong_payer_and_rewritten_full_fact(self):
        g = self.twenty(); self.play(g); saved = self.portable(g)
        for mode in ('missing', 'none', 'quantity', 'records', 'payer', 'phase_type', 'selected'):
            bad = deepcopy(saved); stage = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            f = stage['player_draws']
            if mode == 'missing': del stage['player_draws']
            elif mode == 'none': stage['player_draws'] = None
            elif mode == 'quantity': f['quantity'] += 1
            elif mode == 'records': f['records'] = []
            elif mode == 'payer': f['player_id'] = 2
            elif mode == 'phase_type': f['records'][0]['phase'] = True
            else: f['selected_ids'][0] = True
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())

    def test_original_quote_rechecks_full_phase_while_compact_history_permits_legal_progress(self):
        g = self.one(); stage = self.fact(g).intrinsic
        validate_intrinsic_origin(stage, g.state, g.registry)
        first, *rest = stage.player_draws.records
        changed = replace(stage, player_draws=replace(stage.player_draws,
            records=(replace(first, phase='drawing'), *rest)))
        # The exact live quotation window includes the captured phase. Compact
        # retained history can only prove that this earlier phase may advance.
        with self.assertRaises(ValueError): validate_intrinsic_origin(changed, g.state, g.registry)
        validate_intrinsic_history_prefix(changed, g.state, g.registry)
        self.assertEqual(changed.amount, stage.amount)

    def test_ordinary_cards_require_explicit_none_in_dictionary_and_typed_stage(self):
        g = self.game(); f = capture_generated_quote_fact(g.state, g.registry, 1, 'card.1').intrinsic
        self.assertIsNone(f.player_draws)
        wire = json.loads(json.dumps(asdict(f))); del wire['player_draws']
        with self.assertRaises(ValueError): _intrinsic_stage_from_dict(wire)
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        wire = codec.encode(f); del wire['fields']['player_draws']
        with self.assertRaises(ValueError): codec.decode(wire)

    def test_opening_dealing_and_mulligan_are_excluded_but_first_normal_draw_counts(self):
        r = registry(); g = Game.from_decks(setup(r), r)
        self.assertFalse(g.state.draw_history)
        self.assertEqual(capture_generated_quote_fact(g.state, r, 1, GIANT).amount, 25)
        while g.state.pending_choice is not None:
            q = g.state.pending_choice
            g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual((len(g.state.draw_history), capture_generated_quote_fact(g.state, r, 1, GIANT).amount), (1, 24))
        self.portable(g)

    def test_quotes_and_player_views_are_pure_and_hide_original_history_and_facts(self):
        g = self.one(); before = g.snapshot()
        for _ in range(2):
            self.assertEqual(self.price(g), 24)
            capture_generated_quote_fact(g.state, g.registry, 1, GIANT)
            for player in (1, 2):
                text = json.dumps(g.observe(player))
                for hidden in ('player_draws', 'draw_history', 'selected_ids', 'cast_history_length', 'submitted_cost'):
                    self.assertNotIn(hidden, text)
        self.assertEqual(g.snapshot(), before)

    def test_new_strict_schema_and_rule_versions_reject_original_or_future_layouts(self):
        g = self.one(); saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']), ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        for version in (1, 201, 217, True):
            bad = deepcopy(saved); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())


if __name__ == '__main__': unittest.main()
