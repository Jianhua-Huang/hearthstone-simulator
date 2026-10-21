"""Floating Lessons uses original quotes, native CAST origins and ordinary buffs."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.constructed import build_registry
from hs_sim.cards.source_cost_stat_spell_card import CARD, BODY as PAYLOAD, load_batch
from hs_sim.engine import (CardDefinition, CardType, CounterSpell, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SetSecret, SnapshotError)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddCostModifier, ChangeControl, ChoiceOption, GainArmor, InvokeBehavior,
    ModifyCost, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass, CardMetadata, CostSpec, LimitedTriggerSpec,
    PaymentType, SecretSpec, TriggerSpec, Zone)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell
from hs_sim.engine.spell_source_costs import SpellSourceCostProfile, validate_record
from hs_sim.engine.zones import CardReference
from tools.card_batch import check_face

P = 'fixture.source_cost.'
MINION, WAIT, FAULT, SECRET = (P+x for x in ('minion', 'wait', 'fault', 'secret'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None)


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent registry role required')
    r = build_registry()
    r.register_card(CardDefinition(MINION, MINION, CardType.MINION, attack=1, health=6, metadata=META))
    def fail(c): raise ResolutionError('Explicit source-cost spell failure')
    r.register_behavior(P+'fail', fail)
    def held(c, pid=None, zone='hand'):
        pid = c.player_id if pid is None else pid
        return next(c.state.entities[i] for i in getattr(c.state.players[pid], zone) if c.state.entities[i].card_id == CARD)
    def target(c):
        return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == MINION)
    def automatic(c):
        return (CastSpell(c.player_id, CARD, c.source_id, target(c) if c.state.players[c.player_id].board else None,
            targeting='explicit', choices='player'),)
    def stored(c, pid=None, zone='hand'):
        entity = held(c, pid, zone)
        return (CastStoredSpell(CardReference.capture(entity), c.player_id, c.source_id,
            target(c), targeting='explicit', choices='player'),)
    def foreign(c):
        entity = held(c, 3-c.player_id)
        return (ModifyCost(entity.id, CostSpec(set_to=3), c.source_id), *stored(c, 3-c.player_id))
    scripts = {
        'raise': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=3, card_ids=(CARD,)),
            uses_remaining=1, source_id=c.source_id),),
        'discount': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-1, card_ids=(CARD,)),
            uses_remaining=1, source_id=c.source_id),),
        'local': lambda c: (ModifyCost(held(c).id, CostSpec(set_to=5), c.source_id),),
        'health': lambda c: (ModifyCost(held(c).id, CostSpec(set_to=3, payment=PaymentType.HEALTH), c.source_id),),
        'auto': automatic, 'stored': stored, 'foreign': foreign,
        'deck': lambda c: stored(c, zone='deck'),
        'bad': lambda c: (InvokeBehavior(PAYLOAD, c.source_id, c.player_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'arm': lambda c: (SetSecret(3-c.player_id, SECRET),),
    }
    for key, body in scripts.items():
        cid = P+key; r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=key == 'silence', metadata=META))
    r.register_trigger_condition(P+'original', lambda c: c.event.source_id is not None and
        c.state.entities[c.event.source_id].card_id == CARD)
    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('raise', 'Later price change', (AddCostModifier(c.player_id,
                CostSpec(delta=9, card_ids=(CARD,)), source_id=c.source_id),)),
            ChoiceOption('bounce', 'Return original target', (ReturnToHand(c.event.target_id),)),
            ChoiceOption('control', 'Change target controller', (ChangeControl(c.event.target_id, 3-c.player_id),)),
            ChoiceOption('fail', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(P+'fail', c.source_id, c.player_id))),
        ), c.source_id),)
    r.register_behavior(P+'wait', wait)
    r.register_card(CardDefinition(WAIT, WAIT, CardType.MINION, health=20,
        limited_triggers=(LimitedTriggerSpec('spell_cast_started', P+'wait', condition_id=P+'original'),), metadata=META))
    r.register_behavior(P+'end_fail', lambda c: (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if c.state.entities[c.event.source_id].card_id == CARD else ())
    r.register_card(CardDefinition(FAULT, FAULT, CardType.MINION, health=20,
        triggers=(TriggerSpec('spell_cast_finished', P+'end_fail'),), metadata=META))
    r.register_secret_condition(P+'counter_condition', lambda c: c.window is not None and
        c.window.kind == 'spell' and not c.window.countered and c.window.player_id != c.player_id)
    r.register_behavior(P+'counter', lambda c: (CounterSpell(c.window.id),))
    r.register_card(CardDefinition(SECRET, SECRET, CardType.SPELL, keywords=(Keyword.SECRET,),
        secret=SecretSpec(SECRET, ('card_committed',), P+'counter_condition', P+'counter'), metadata=META))
    return r


class SourceCostStatSpellTests(unittest.TestCase):
    def game(self, hand=(CARD, MINION), board=(MINION,), enemy=(MINION,), actor=1,
             enemy_hand=(), deck=('GAME_005',)*8):
        own = PlayerSetup('HERO_09', hand=hand, board=board, deck=deck, mana=30, max_mana=30, mana_cap=30)
        other = PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=('GAME_005',)*8,
            mana=30, max_mana=30, mana_cap=30)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=351), fixture())

    def board(self, g, pid=None):
        pid = g.state.active_player if pid is None else pid
        return [g.state.entities[i] for i in g.state.players[pid].board]

    def held(self, g, cid=CARD):
        return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id == cid)

    def play(self, g, cid=CARD, target=None):
        pid = g.state.active_player; eid = self.held(g, cid)
        g.apply(PlayCard(pid, eid, target)); return eid

    def casts(self, g): return [r for r in g.state.cast_history if r.card_id == CARD]

    def hand_minions(self, g):
        return [g.state.entities[i] for i in g.state.players[g.state.active_player].hand if g.state.entities[i].kind == CardType.MINION]

    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = g.snapshot(); other = Game.from_snapshot(json.loads(json.dumps(saved)), fixture('reader'))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fixture('reader')).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('"source_cost"', '"quote_input"', '"consumable_ids"', '"resolution_frame"', '"rng_state"'):
                self.assertNotIn(key, public)
        return other

    def test_complete_source_and_both_primary_faces_bind_real_shadow_spell(self):
        data = load_batch(); raw = data['cards'][0]['record']
        for face in data['official_observations']: check_face(raw, face['face'], face['locale'])
        d = fixture().card(CARD)
        self.assertEqual(d.cost, 1); self.assertEqual(d.spell_school.value, 'shadow')
        self.assertIn(CARD, fixture().spell_source_cost_profiles)

    def test_native_manual_payment_and_both_stat_grants_use_original_one_cost(self):
        g = self.game(); target = self.board(g)[0].id; self.play(g, target=target)
        self.assertEqual((g.state.players[1].mana, g.state.entities[target].attack, g.state.entities[target].health), (29, 3, 8))
        self.assertEqual([(e.attack, e.health) for e in self.hand_minions(g)], [(3, 8)])
        self.assertEqual(self.casts(g)[0].source_cost, g.state.play_history[0].submitted_cost.quote); self.portable(g)

    def test_one_use_increase_is_consumed_but_original_cost_four_grows_both_by_eight(self):
        g = self.game((P+'raise', CARD, MINION)); self.play(g, P+'raise'); target = self.board(g)[0].id
        self.play(g, target=target)
        self.assertEqual(self.casts(g)[0].source_cost.amount, 4)
        self.assertEqual((g.state.entities[target].attack, self.hand_minions(g)[0].attack), (9, 9))
        self.assertEqual(g.state.players[1].mana, 26); self.portable(g)

    def test_zero_original_cost_has_no_stat_grants_or_random_draw(self):
        g = self.game((P+'discount', CARD, MINION)); self.play(g, P+'discount')
        before = g._rng.getstate(); self.play(g, target=self.board(g)[0].id)
        self.assertEqual(self.casts(g)[0].source_cost.amount, 0)
        self.assertEqual((self.board(g)[0].attack, self.hand_minions(g)[0].attack), (1, 1))
        self.assertEqual(g._rng.getstate(), before); self.assertEqual(g.state.players[1].mana, 30)

    def test_local_five_cost_is_not_replaced_by_printed_one(self):
        g = self.game((P+'local', CARD, MINION)); self.play(g, P+'local'); self.play(g, target=self.board(g)[0].id)
        self.assertEqual(self.casts(g)[0].source_cost.amount, 5)
        self.assertEqual((self.board(g)[0].attack, self.hand_minions(g)[0].attack), (11, 11))

    def test_health_payment_uses_numeric_quote_not_mana_spent(self):
        g = self.game((P+'health', CARD, MINION)); self.play(g, P+'health')
        before = g.state.entities[g.state.players[1].hero_id].health; self.play(g, target=self.board(g)[0].id)
        self.assertEqual((g.state.players[1].mana, g.state.entities[g.state.players[1].hero_id].health), (30, before-3))
        self.assertEqual((self.board(g)[0].attack, self.hand_minions(g)[0].attack), (7, 7)); self.portable(g)

    def test_free_generated_cast_still_uses_cost_one(self):
        g = self.game((P+'auto', MINION)); self.play(g, P+'auto')
        self.assertEqual((self.casts(g)[0].source_cost.amount, g.state.players[1].mana), (1, 30))
        self.assertEqual((self.board(g)[0].attack, self.hand_minions(g)[0].attack), (3, 3)); self.portable(g)

    def test_free_cast_quotes_live_one_use_increase_without_consuming_it(self):
        g = self.game((P+'raise', P+'auto', CARD, MINION)); self.play(g, P+'raise'); self.play(g, P+'auto')
        self.assertEqual(self.casts(g)[0].source_cost.amount, 4)
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[self.held(g)]).amount, 4)
        self.assertEqual(g.state.players[1].mana, 30)
        self.play(g, target=self.board(g)[0].id)
        self.assertEqual([c.source_cost.amount for c in self.casts(g)], [4, 4]); self.portable(g)

    def test_stored_hand_cost_survives_real_free_cast_and_source_movement(self):
        g = self.game((P+'local', P+'stored', CARD, MINION)); original = self.held(g)
        self.play(g, P+'local'); self.play(g, P+'stored')
        record = self.casts(g)[0]
        self.assertEqual((record.source_id, record.from_zone, record.source_cost.amount), (original, Zone.HAND, 5))
        self.assertEqual((g.state.players[1].mana, self.board(g)[0].attack), (30, 11)); self.portable(g)

    def test_cross_player_stored_source_quotes_for_actual_caster_without_changing_owner(self):
        g = self.game((P+'foreign', MINION), enemy_hand=(CARD,)); self.play(g, P+'foreign')
        row = self.casts(g)[0]; entity = g.state.entities[row.source_id]
        self.assertEqual((entity.owner, entity.controller, row.source_cost.quote_input.player_id, row.source_cost.amount), (2, 1, 1, 3))
        self.assertEqual((self.board(g)[0].attack, self.hand_minions(g)[0].attack), (7, 7)); self.portable(g)

    def test_real_deck_cast_has_one_cost_and_no_payment(self):
        g = self.game((P+'deck', MINION), deck=(CARD, 'GAME_005')); self.play(g, P+'deck')
        self.assertEqual((self.casts(g)[0].from_zone, self.casts(g)[0].source_cost.amount), (Zone.DECK, 1)); self.portable(g)

    def test_actual_niri_automatic_repeat_has_its_own_complete_source_cost_and_start_receipt(self):
        g = self.game((P+'auto', MINION), board=(MINION, 'TLC_836')); self.play(g, P+'auto')
        rows = self.casts(g); self.assertEqual([r.origin for r in rows], ['effect', 'native_repeat'])
        self.assertEqual([r.source_cost.amount for r in rows], [1, 1])
        self.assertEqual((self.board(g)[0].attack, self.hand_minions(g)[0].attack), (5, 5)); self.portable(g)

    def test_second_seat_and_enemy_minion_are_valid_original_targets(self):
        g = self.game(actor=2); target = self.board(g, 1)[0].id; self.play(g, target=target)
        self.assertEqual((g.state.entities[target].attack, self.hand_minions(g)[0].attack), (3, 3))
        self.assertEqual(self.casts(g)[0].source_cost.quote_input.player_id, 2); self.portable(g)

    def test_random_hand_grant_selects_one_physical_minion(self):
        g = self.game((CARD, MINION, MINION, 'GAME_005')); self.play(g, target=self.board(g)[0].id)
        self.assertEqual(sorted(e.attack for e in self.hand_minions(g)), [1, 3]); self.portable(g)

    def test_no_hand_minion_still_grows_board_and_does_not_advance_rng(self):
        g = self.game((CARD, 'GAME_005')); before = g._rng.getstate(); self.play(g, target=self.board(g)[0].id)
        self.assertEqual(self.board(g)[0].attack, 3); self.assertEqual(g._rng.getstate(), before)

    def test_hand_growth_remains_on_actual_play_and_can_then_be_silenced(self):
        g = self.game((CARD, MINION, P+'silence')); self.play(g, target=self.board(g)[0].id)
        source = self.play(g, MINION); self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 8))
        self.play(g, P+'silence', source); self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (1, 6))

    def test_start_wait_restores_and_later_price_changes_cannot_reprice_accepted_payload(self):
        g = self.game(board=(MINION, WAIT)); self.play(g, target=self.board(g)[0].id)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.board(g)[0].attack, 1)
        other = self.portable(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit source-cost spell failure'): self.choose(other, 'fail')
        self.assertEqual(other.snapshot(), saved)
        for game in (g, other): self.choose(game, 'raise')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((self.board(g)[0].attack, self.hand_minions(g)[0].attack, self.casts(g)[0].source_cost.amount), (3, 3, 1)); self.portable(g)

    def test_returned_original_board_target_is_not_board_buffed_but_can_be_the_hand_recipient(self):
        g = self.game((CARD,), board=(MINION, WAIT)); target = self.board(g)[0].id; self.play(g, target=target)
        self.choose(g, 'bounce'); self.assertEqual(g.state.entities[target].zone, Zone.HAND)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (3, 8)); self.portable(g)

    def test_end_failure_rolls_back_payment_both_grants_and_original_source_record(self):
        g = self.game(board=(MINION, FAULT)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit source-cost spell failure'): self.play(g, target=self.board(g)[0].id)
        self.assertEqual(g.snapshot(), saved)

    def test_original_any_side_target_can_change_control_before_the_ordinary_buff(self):
        g = self.game(board=(MINION, WAIT)); target = self.board(g)[0].id
        self.play(g, target=target); self.choose(g, 'control')
        self.assertEqual((g.state.entities[target].controller, g.state.entities[target].attack), (2, 3))
        self.assertEqual(self.hand_minions(g)[0].attack, 3); self.portable(g)

    def test_native_repeat_of_returned_original_target_skips_board_part_and_keeps_hand_part(self):
        g = self.game((P+'auto',), board=(MINION, 'TLC_836', WAIT)); target = self.board(g)[0].id
        self.play(g, P+'auto'); self.choose(g, 'bounce')
        self.assertEqual([r.origin for r in self.casts(g)], ['effect', 'native_repeat'])
        self.assertEqual((g.state.entities[target].zone, g.state.entities[target].attack), (Zone.HAND, 5))
        self.portable(g)

    def test_no_target_automatic_attempt_keeps_quote_but_does_not_buff_hand(self):
        g = self.game((P+'auto', MINION), board=()); self.play(g, P+'auto')
        row = self.casts(g)[0]; self.assertEqual(row.failure, 'no_target'); self.assertEqual(row.source_cost.amount, 1)
        self.assertEqual(self.hand_minions(g)[0].attack, 1); self.portable(g)

    def test_countered_paid_spell_keeps_original_quote_and_applies_no_grants(self):
        g = self.game((P+'arm', CARD, MINION)); self.play(g, P+'arm'); self.play(g, target=self.board(g)[0].id)
        row = self.casts(g)[0]; self.assertEqual((row.failure, row.source_cost.amount), ('countered', 1))
        self.assertEqual((self.board(g)[0].attack, self.hand_minions(g)[0].attack), (1, 1)); self.portable(g)

    def test_direct_body_on_an_undeclared_spell_is_an_explicit_error(self):
        g = self.game((P+'bad',)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'declared original cost'): self.play(g, P+'bad')
        self.assertEqual(g.snapshot(), saved)

    def test_rehashed_saved_cost_missing_or_borrowed_original_input_is_rejected(self):
        g = self.game(); self.play(g, target=self.board(g)[0].id)
        for mode in ('missing', 'null', 'source', 'payer', 'amount'):
            snap = g.snapshot(); row = next(r for r in snap['state']['cast_history'] if r['card_id'] == CARD)
            if mode == 'missing': del row['source_cost']
            elif mode == 'null': row['source_cost'] = None
            elif mode == 'source': row['source_cost']['quote_input']['source_id'] += 1
            elif mode == 'payer': row['source_cost']['quote_input']['player_id'] = 2
            else: row['source_cost']['amount'] += 1
            snap['state_hash'] = canonical_hash({k:v for k,v in snap.items() if k not in
                ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(snap, fixture('reader'))

    def test_original_start_receipt_digest_is_checked_after_both_outer_hashes_are_recomputed(self):
        g = self.game(); self.play(g, target=self.board(g)[0].id); snap = g.snapshot()
        event = next(e for e in snap['events'] if e['kind'] == 'spell_cast_started' and 'source_cost' in e['data'])
        event['data']['source_cost'] = '0'*64; snap['events_hash'] = canonical_hash(snap['events'])
        snap['state_hash'] = canonical_hash({k:v for k,v in snap.items() if k not in
            ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, 'source cost differs'): Game.from_snapshot(snap, fixture('reader'))

    def test_profile_and_schema_are_explicit_and_old_wires_cannot_omit_source_cost(self):
        with self.assertRaises(ValueError): SpellSourceCostProfile(CARD, basis='amount_paid')
        r = build_registry()
        with self.assertRaises(ValueError): r.register_spell_source_cost_profile(SpellSourceCostProfile(CARD))
        g = self.game(); self.assertEqual(g.snapshot()['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        for version in (508, True, float(SNAPSHOT_SCHEMA_VERSION), SNAPSHOT_SCHEMA_VERSION+1):
            snap = g.snapshot(); snap['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(snap, fixture('reader'))
