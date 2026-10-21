"""Aqir Hulk prices original submitted Combo cards, never Combo executions."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.constructed import build_registry
from hs_sim.cards.combo_play_turn_cost_card import CARD, PROFILE, load_batch
from hs_sim.engine import (CardDefinition, CardType, CounterMinion, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SetSecret, SnapshotError)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact,
    capture_quote_fact, quote_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, CopyMinion,
    GainArmor, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand,
    Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass, CardMetadata, CostSpec, LimitedTriggerSpec,
    PaymentType, PlayerPlayedClassCostSpec, SecretSpec, TriggerSpec, Zone)
from hs_sim.engine.play_history import matches_played_combo
from hs_sim.engine.player_played_class_costs import validate_prefix
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from tools.card_batch import check_face

P = 'fixture.combo_price.'
MINION, SPELL = 'CORE_EX1_134', 'EX1_124'
BODY, WAIT, FAULT, SECRET = (P+x for x in ('body', 'wait', 'fault', 'secret'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None)


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent registry role required')
    r = build_registry(); r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(BODY, BODY, CardType.MINION, attack=1, health=20, metadata=META))
    def fail(c): raise ResolutionError('Explicit Combo-card price failure')
    r.register_behavior(P+'fail', fail)
    def held(c):
        return next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == CARD)
    operations = {
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'transform': lambda c: (Transform(c.target_id, BODY),),
        'summon': lambda c: (Summon(c.player_id, MINION),),
        'auto': lambda c: (CastSpell(c.player_id, SPELL, c.source_id),),
        'get': lambda c: (AddToHand(c.player_id, CARD, c.source_id),),
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'layers': lambda c: (ModifyCost(held(c), CostSpec(delta=-1), c.source_id),
            AddCostModifier(c.player_id, CostSpec(delta=2, card_ids=(CARD,)), uses_remaining=1, source_id=c.source_id)),
        'health': lambda c: (ModifyCost(held(c), CostSpec(payment=PaymentType.HEALTH), c.source_id),),
        'arm': lambda c: (SetSecret(3-c.player_id, SECRET),),
    }
    for key, body in operations.items():
        cid = P+key; r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=key in ('bounce', 'silence', 'transform', 'copy'), metadata=META))
    r.register_secret_condition(P+'counter_condition', lambda c: c.window is not None and
        c.window.kind == 'minion' and not c.window.countered and c.window.player_id != c.player_id)
    r.register_behavior(P+'counter', lambda c: (CounterMinion(c.window.id),))
    r.register_card(CardDefinition(SECRET, SECRET, CardType.SPELL, keywords=(Keyword.SECRET,),
        secret=SecretSpec(SECRET, ('minion_counter_check',), P+'counter_condition', P+'counter'), metadata=META))
    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'), ChoiceOption('get', 'Another Hulk', (AddToHand(c.player_id, CARD, c.source_id),)),
            ChoiceOption('fail', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(P+'fail', c.source_id, c.player_id))),
        ), c.source_id),)
    r.register_behavior(P+'wait', wait)
    r.register_trigger_condition(P+'hulk', lambda c: c.state.entities[c.event.source_id].card_id == CARD)
    r.register_card(CardDefinition(WAIT, WAIT, CardType.MINION, health=20,
        limited_triggers=(LimitedTriggerSpec('card_played', P+'wait', condition_id=P+'hulk'),), metadata=META))
    r.register_card(CardDefinition(FAULT, FAULT, CardType.MINION, health=20,
        triggers=(TriggerSpec('card_drawn', P+'fail'),), metadata=META))
    return r


class ComboPlayTurnCostTests(unittest.TestCase):
    def game(self, hand=(MINION, CARD), board=(), enemy_hand=(), actor=1, mana=30):
        own = PlayerSetup('HERO_03', hand=hand, board=board, deck=('GAME_005',)*8,
            mana=mana, max_mana=30, mana_cap=30)
        other = PlayerSetup('HERO_08', hand=enemy_hand, deck=('GAME_005',)*8,
            mana=30, max_mana=30, mana_cap=30)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=350), fixture())

    def hand_id(self, g, cid=CARD, pid=None):
        pid = g.state.active_player if pid is None else pid
        return next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        pid = g.state.active_player; eid = self.hand_id(g, cid)
        g.apply(PlayCard(pid, eid, target)); return eid

    def price(self, g, pid=None):
        pid = g.state.active_player if pid is None else pid
        return quote_cost(g.state, g.registry, g.state.entities[self.hand_id(g, pid=pid)]).amount

    def fact(self, g):
        eid = self.hand_id(g)
        return capture_quote_fact(g.state, g.registry, capture_cost_input(g.state.entities[eid])).intrinsic.player_played_class

    def hero(self, g, pid=2): return g.state.players[pid].hero_id

    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = g.snapshot(); other = Game.from_snapshot(json.loads(json.dumps(saved)), fixture('reader'))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fixture('reader')).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('"combo_inputs"', '"selected_ids"', '"quote_input"', '"resolution_frame"', '"rng_state"'):
                self.assertNotIn(key, public)
        return other

    def test_complete_original_and_bilingual_faces_match_real_cost_and_draw(self):
        data = load_batch(); raw = data['cards'][0]['record']
        for f in data['official_observations']: check_face(raw, f['face'], f['locale'])
        d = fixture().card(CARD)
        self.assertEqual((d.cost, d.attack, d.health, d.metadata.tribes), (8, 4, 5, ('beast',)))
        self.assertEqual(d.player_played_class_cost, PlayerPlayedClassCostSpec(card_class=None, profile_id=PROFILE))

    def test_first_unactivated_real_combo_minion_still_reduces_two_and_native_draw_pays_once(self):
        g = self.game(); self.assertEqual(self.price(g), 8)
        self.play(g, MINION); self.assertFalse(g.state.play_history[0].combo); self.assertFalse(g.state.combo_history)
        self.assertEqual((self.price(g), self.fact(g).quantity), (6, 1))
        before = g.state.players[1].mana; deck = len(g.state.players[1].deck); source = self.play(g, CARD)
        record = g.state.play_history[-1]
        self.assertEqual((before-g.state.players[1].mana, record.cost, len(g.state.players[1].deck)), (6, 6, deck-1))
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (4, 5))
        self.assertEqual(record.submitted_cost.quote.intrinsic.player_played_class.quantity, 1); self.portable(g)

    def test_real_combo_spell_keyword_counts_without_a_minion_combo_payload(self):
        g = self.game((SPELL, CARD)); self.play(g, SPELL, self.hero(g))
        self.assertFalse(g.state.play_history[0].combo); self.assertFalse(g.state.play_history[0].combos)
        self.assertTrue(matches_played_combo(g.state.play_history[0].submitted_cost.quote.quote_input))
        self.assertEqual(self.price(g), 6); self.portable(g)

    def test_combo_activations_are_not_extra_played_cards(self):
        g = self.game((MINION, MINION, CARD)); self.play(g, MINION)
        self.play(g, MINION, self.hero(g)); self.assertEqual(len(g.state.combo_history), 1)
        self.assertEqual((self.fact(g).selected_ids, self.fact(g).quantity, self.price(g)), ((1, 2), 2, 4))

    def test_discount_clamps_at_zero_without_truncating_complete_count(self):
        g = self.game((MINION,)*5+(CARD,))
        for n in range(5): self.play(g, MINION, None if n == 0 else self.hero(g))
        self.assertEqual((self.fact(g).quantity, self.fact(g).selected_ids, self.price(g)), (5, (1, 2, 3, 4, 5), 0))
        mana = g.state.players[1].mana; self.play(g, CARD); self.assertEqual(g.state.players[1].mana, mana)

    def test_non_combo_hand_roots_do_not_discount(self):
        g = self.game((P+'get', CARD)); self.play(g, P+'get')
        self.assertEqual((self.fact(g).quantity, self.price(g)), (0, 8))

    def test_automatic_cast_and_summoned_combo_minion_do_not_add_qualifying_hand_roots(self):
        for cid in (P+'auto', P+'summon'):
            with self.subTest(cid=cid):
                g = self.game((cid, CARD)); self.play(g, cid)
                self.assertEqual((self.fact(g).quantity, self.price(g)), (0, 8)); self.portable(g)

    def test_countered_paid_combo_root_still_counts_without_activation(self):
        g = self.game((P+'arm', MINION, CARD)); self.play(g, P+'arm'); self.play(g, MINION, self.hero(g))
        self.assertTrue(g.state.play_history[-1].countered); self.assertFalse(g.state.combo_history)
        self.assertEqual((self.fact(g).selected_ids, self.price(g)), ((2,), 6)); self.portable(g)

    def test_later_silence_or_transform_does_not_reclassify_original_combo_card(self):
        for operation in ('silence', 'transform'):
            with self.subTest(operation=operation):
                g = self.game((MINION, P+operation, CARD)); source = self.play(g, MINION)
                self.play(g, P+operation, source)
                self.assertEqual((self.fact(g).quantity, self.price(g)), (1, 6)); self.portable(g)

    def test_returning_same_physical_combo_card_and_replaying_adds_another_root(self):
        g = self.game((MINION, P+'bounce', CARD)); source = self.play(g, MINION)
        self.play(g, P+'bounce', source); self.assertEqual(self.price(g), 6)
        again = self.play(g, MINION, self.hero(g)); self.assertEqual(again, source)
        self.assertEqual((self.fact(g).quantity, self.fact(g).selected_ids, self.price(g)), (2, (1, 3), 4)); self.portable(g)

    def test_prior_global_turn_and_other_player_roots_do_not_discount(self):
        g = self.game(enemy_hand=(SPELL,)); self.play(g, MINION); g.apply(EndTurn(1))
        self.play(g, SPELL, self.hero(g, 1)); self.assertEqual(self.price(g, 1), 8)
        g.apply(EndTurn(2)); self.assertEqual((self.fact(g).quantity, self.price(g)), (0, 8)); self.portable(g)

    def test_second_seat_uses_actual_payer_history(self):
        g = self.game(actor=2); self.play(g, MINION); self.assertEqual((self.price(g), self.fact(g).player_id), (6, 2))
        self.play(g, CARD); self.portable(g)

    def test_acquired_after_combo_and_generated_quote_reuse_same_original_inputs(self):
        g = self.game((MINION, P+'get')); self.play(g, MINION); self.play(g, P+'get')
        generated = capture_generated_quote_fact(g.state, g.registry, 1, CARD)
        self.assertEqual((generated.amount, self.price(g)), (6, 6))
        self.assertEqual(generated.intrinsic.player_played_class.combo_inputs, self.fact(g).combo_inputs)

    def test_local_and_external_price_layers_follow_intrinsic_discount_and_pay_once(self):
        g = self.game((MINION, P+'layers', CARD)); self.play(g, MINION); self.play(g, P+'layers')
        self.assertEqual(self.price(g), 7); self.assertEqual(g.state.entities[self.hand_id(g)].base_cost, 8)
        before = g.state.players[1].mana; self.play(g, CARD)
        quote = g.state.play_history[-1].submitted_cost.quote
        self.assertEqual((quote.intrinsic.amount, quote.local_amount, quote.amount, before-g.state.players[1].mana), (6, 5, 7, 7))
        self.portable(g)

    def test_health_payment_uses_same_discount_and_original_account(self):
        g = self.game((MINION, P+'health', CARD)); self.play(g, MINION); self.play(g, P+'health')
        before = g.state.entities[self.hero(g, 1)].health; mana = g.state.players[1].mana
        self.play(g, CARD)
        self.assertEqual((g.state.entities[self.hero(g, 1)].health, g.state.players[1].mana), (before-6, mana))
        self.assertEqual(g.state.play_history[-1].payment, PaymentType.HEALTH); self.portable(g)

    def test_pure_repeated_quotes_do_not_consume_rng_or_rewrite_base_cost(self):
        g = self.game(); self.play(g, MINION); saved = g.snapshot()
        for _ in range(3): self.assertEqual(self.price(g), 6); self.fact(g)
        self.assertEqual(g.snapshot(), saved)

    def test_paid_wait_roundtrip_late_failure_and_later_new_combo_preserve_original_payment_fact(self):
        g = self.game((MINION, CARD, SPELL), board=(WAIT,)); self.play(g, MINION); self.play(g, CARD)
        self.assertIsNotNone(g.state.pending_choice); old = g.state.play_history[-1].submitted_cost.quote.intrinsic.player_played_class
        other = self.portable(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit Combo-card price failure'): self.choose(other, 'fail')
        self.assertEqual(other.snapshot(), saved)
        for game in (g, other): self.choose(game, 'get'); self.play(game, SPELL, self.hero(game))
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(self.price(g), 4)
        self.assertEqual(g.state.play_history[1].submitted_cost.quote.intrinsic.player_played_class, old)
        self.portable(g)

    def test_failed_native_battlecry_draw_rolls_back_full_payment_and_hand_root(self):
        g = self.game((CARD,), board=(FAULT,)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit Combo-card price failure'): self.play(g, CARD)
        self.assertEqual(g.snapshot(), saved)

    def test_insufficient_payment_does_not_create_a_hand_root(self):
        g = self.game((CARD,), mana=7); saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, CARD)
        self.assertEqual(g.snapshot(), saved)

    def test_full_input_prefix_and_two_per_selected_root_are_strict(self):
        g = self.game(); self.play(g, MINION); f = self.fact(g)
        for changes in ({'combo_inputs': None}, {'combo_inputs': ()}, {'combo_inputs': list(f.combo_inputs)},
                {'quantity': True}, {'selected_ids': ()}, {'after': 7}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(f, **changes)
        empty = replace(f.combo_inputs[0], abilities=())
        forged = replace(f, combo_inputs=(empty,), selected_ids=(), quantity=0, after=8)
        with self.assertRaisesRegex(ValueError, 'submitted physical input prefix'): validate_prefix(forged, g.state, g.registry)
        with self.assertRaises(ValueError): PlayerPlayedClassCostSpec(profile_id=PROFILE)

    def test_rehashed_paid_inputs_missing_operands_and_selection_rewrites_are_rejected(self):
        g = self.game(); self.play(g, MINION); self.play(g, CARD)
        for mutation in ('missing', 'null', 'empty', 'source', 'abilities', 'selected', 'step'):
            snap = g.snapshot(); f = snap['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['player_played_class']
            if mutation == 'missing': del f['combo_inputs']
            elif mutation == 'null': f['combo_inputs'] = None
            elif mutation == 'empty': f['combo_inputs'] = []
            elif mutation == 'source': f['combo_inputs'][0]['source_id'] += 1
            elif mutation == 'abilities': f['combo_inputs'][0]['abilities'] = []
            elif mutation == 'selected': f['selected_ids'] = []
            else: f['after'] = 7
            snap['state_hash'] = canonical_hash({k:v for k,v in snap.items() if k not in
                ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.subTest(mutation=mutation), self.assertRaises(SnapshotError): Game.from_snapshot(snap, fixture('reader'))

    def test_new_schema_is_strict_and_old_saved_effect_signatures_are_rejected(self):
        g = self.game(); self.assertEqual(SNAPSHOT_SCHEMA_VERSION, 508)
        for version in (507, True, 508.0, 509):
            snap = g.snapshot(); snap['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(snap, fixture('reader'))
