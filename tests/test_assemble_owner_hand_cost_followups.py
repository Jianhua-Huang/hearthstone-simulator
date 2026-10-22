"""Real owner-end sources keep their own gates and reuse native hand effects."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import assemble_owner_hand_cost_followups as cards
from hs_sim.cards.native_assemble_entry_cards import SHAPER, POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleRecipe, validate_template
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    GainArmor, GainTemporaryMana, InvokeBehavior, RequestChoice, SpendMana)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import EndTurnSpec, TribeChangeSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_damage_health_followups import fixture as base_fixture
from test_assemble_card_play_followups import META, COIN, KILL, MUTE, LOOT

TRADER, NANNY = cards.SOURCES
FIRE = 'CORE_UNG_809'
BEETLE = 'CORE_LOOT_413'
P = 'k436.'
BEAST, PLAIN, UNKNOWN, BECOME, REMOVE, GIVE, COPY, BASE_COPY, PRELUDE, WATCH, FAIL = (
    P + name for name in ('beast', 'plain', 'unknown', 'become', 'remove', 'give',
                         'copy', 'base_copy', 'prelude', 'watch', 'fail'))
CTX = GenerationContext('k436-explicit-original-owner-end-domains', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role); r._version += '.k436.' + mode
    for cid, tribes in ((BEAST, ('beast',)), (PLAIN, ()), (UNKNOWN, None)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=4, attack=1,
            health=8, metadata=replace(META, tribes=tribes)))
    for cid, hand_card, operation, tribes in ((BECOME, PLAIN, 'set', ('beast',)),
                                             (REMOVE, BEAST, 'remove', ('beast',))):
        def change(c, hand_card=hand_card, operation=operation, tribes=tribes):
            eid = next(i for i in c.state.players[c.player_id].hand
                       if c.state.entities[i].card_id == hand_card)
            return (ChangeMinionTribes(CardReference.capture(c.state.entities[eid]),
                TribeChangeSpec(operation, tribes), c.source_id),)
        r.register_behavior(cid, change)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META))
    r.register_behavior(GIVE, lambda c: (ChangeControl(c.target_id, 3-c.player_id),))
    for cid, copy_mode in ((COPY, 'current'), (BASE_COPY, 'base')):
        r.register_behavior(cid, lambda c, copy_mode=copy_mode:
            (CopyMinion(c.target_id, c.player_id, mode=copy_mode),))
    for cid in (GIVE, COPY, BASE_COPY):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    def fail(c): raise ResolutionError('K436 deliberate owner-end continuation failure')
    r.register_behavior(FAIL, fail)
    def choices(c):
        return (ChoiceOption('go', 'Continue'),
            ChoiceOption('gain', 'Gain one temporary mana', (GainTemporaryMana(c.player_id, 1),)),
            ChoiceOption('spend', 'Spend one mana', (SpendMana(c.player_id, 1, c.source_id),)),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id))))
    r.register_behavior(PRELUDE, lambda c: (RequestChoice(c.player_id, choices(c), c.source_id),))
    r.register_card(CardDefinition(PRELUDE, PRELUDE, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('turn_ended', PRELUDE, EndTurnSpec()),)))
    def watch(c):
        return (RequestChoice(c.player_id, choices(c) + (ChoiceOption('depart', 'Source leaves',
            (Destroy(c.event.source_id, c.source_id),)),), c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('stored_card_buffed', WATCH),)))
    if mode == 'offer':
        r.register_pool(PoolDefinition(POOL_ID, 'k436-current-hunter-nanny-and-two-neutral-sources',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (NANNY, LOOT, BEETLE)), complete=True))
    r.validate(); return r


class AssembleOwnerHandCostTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy_hand=(), mana=30, mode='normal', deck=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_05' if mode == 'offer' else 'HERO_06', hand=hand, board=board, deck=deck or (COIN,) * 24,
                mana=mana, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=(COIN,) * 24,
                mana=30, max_mana=30, mana_cap=30)), seed=1, generation_context=CTX), fixture(mode))

    def eid(self, g, cid, zone='hand', player=1):
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        eid = self.eid(g, cid); g.apply(PlayCard(1, eid, target)); return eid

    def price(self, g, cid, player=1, zone='hand'):
        return quote_unselected_cost(g.state, g.registry,
            g.state.entities[self.eid(g, cid, zone, player)]).amount

    def count(self, g, cid=COIN, player=1, zone='hand'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[player], zone))

    def pick(self, g, key='go'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry)
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'primary_candidates', 'CardReference'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a_two_full_rows_four_faces_exact_original_clocks_and_self_noops(self):
        d = cards.load_batch(); r = fixture(); rows = {x['record']['id']: x for x in d['existing_dependencies']}
        self.assertEqual(len(rows), 2); self.assertEqual(len(d['official_observations']), 4)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
        before = r.fingerprint()
        for cid in cards.SOURCES:
            old = r.card(cid); new = r.card(recipe(cid)); t = r.assemble_templates[cid]
            self.assertEqual(canonical_digest(asdict(old)), rows[cid]['definition_sha256'])
            self.assertEqual((new.cost, new.attack, new.health, new.metadata),
                (old.cost, old.attack, old.health, old.metadata))
            self.assertEqual(t.original_end_turn_id, old.triggers[0].behavior_id)
            self.assertEqual(recipe_options(r, cid, cid), ())
        self.assertEqual(r.fingerprint(), before)
        self.assertIsNone(r.assemble_templates[NANNY].prefix.condition_id)

    def test_b_paid_trader_original_and_self_require_actual_remaining_mana_and_owner_end(self):
        for cid in (TRADER, recipe(TRADER)):
            for mana, expected in ((2, 0), (3, 1)):
                g = self.game((cid,), mana=mana); self.play(g, cid)
                self.assertEqual(g.state.players[1].mana, mana-2)
                g.apply(EndTurn(1)); self.assertEqual(self.count(g), expected)
                g.apply(EndTurn(2)); self.assertEqual(self.count(g), expected+1)

    def test_c_original_callback_mana_view_matches_native_despite_later_choice_changes(self):
        for cid in (TRADER, recipe(TRADER)):
            for mana, decision, expected in ((0, 'gain', 0), (1, 'spend', 1)):
                g = self.game(board=(PRELUDE, cid), mana=mana); g.apply(EndTurn(1))
                other = self.portable(g); saved = g.snapshot()
                with self.assertRaises(ResolutionError): self.pick(g, 'bad')
                self.assertEqual(g.snapshot(), saved)
                self.pick(g, decision); self.pick(other, decision)
                self.assertEqual(self.count(g), expected, (cid,mana,decision))
                self.assertEqual(g.snapshot(), other.snapshot())

    def test_d_transferred_trader_uses_new_controller_clock_and_mana(self):
        cid = recipe(TRADER); g = self.game((GIVE,), (cid,), mana=0)
        source = self.eid(g, cid, 'board'); self.play(g, GIVE, source)
        g.apply(EndTurn(1)); self.assertEqual(self.count(g), 0)
        old = self.count(g, player=2); g.apply(EndTurn(2))
        self.assertEqual(self.count(g, player=2), old+1); self.assertEqual(self.count(g), 1)

    def test_e_original_and_self_nanny_filter_current_hand_not_printed_deck_board_or_opponent(self):
        for cid in (NANNY, recipe(NANNY)):
            g = self.game((PLAIN, BEAST, BECOME, REMOVE), (cid, BEAST), (BEAST,), deck=(BEAST,) * 8)
            self.play(g, BECOME); self.play(g, REMOVE); g.apply(EndTurn(1))
            self.assertEqual(self.price(g, PLAIN), 3); self.assertEqual(self.price(g, BEAST), 4)
            self.assertEqual(self.price(g, BEAST, 2), 4); self.assertEqual(self.price(g, BEAST, zone='deck'), 4)
            self.assertEqual(g.registry.card(PLAIN).metadata.tribes, ())

    def test_f_nanny_has_no_unused_mana_gate_discount_persists_and_actual_payment_matches(self):
        for cid in (NANNY, recipe(NANNY)):
            g = self.game((BEAST,), (cid,), mana=0); g.apply(EndTurn(1))
            self.assertEqual(self.price(g, BEAST), 3); g.apply(EndTurn(2))
            self.assertEqual(self.price(g, BEAST), 3)
            old = g.state.players[1].mana; self.play(g, BEAST)
            self.assertEqual(g.state.players[1].mana, old-3)

    def test_g_silence_and_death_remove_only_the_live_nanny_end_source(self):
        cid = recipe(NANNY)
        for remove in (MUTE, KILL):
            g = self.game((remove, BEAST), (cid,)); self.play(g, remove, self.eid(g, cid, 'board'))
            g.apply(EndTurn(1)); self.assertEqual(self.price(g, BEAST), 4)

    def test_h_borrowed_nanny_death_body_is_guard_free_and_has_no_end_clock(self):
        cid = recipe(NANNY, LOOT, 'top'); g = self.game((cid, KILL, BEAST))
        source = self.play(g, cid); self.play(g, KILL, source)
        self.assertEqual(self.price(g, BEAST), 3)
        g.apply(EndTurn(1)); self.assertEqual(self.price(g, BEAST), 3)

    def test_i_borrowed_trader_battlecry_draws_at_zero_mana_without_old_end_condition(self):
        cid = recipe(FIRE, TRADER); g = self.game((cid,), mana=1); self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, 0); self.assertEqual(self.count(g), 1)
        g.apply(EndTurn(1)); self.assertEqual(self.count(g), 1)

    def test_j_trader_prefix_keeps_mana_gate_but_only_runs_selected_armor_body(self):
        cid = recipe(TRADER, BEETLE)
        for mana, expected in ((0, 0), (1, 3)):
            g = self.game(board=(cid,), mana=mana); g.apply(EndTurn(1))
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, expected)
            self.assertEqual(self.count(g), 0)

    def test_k_plain_nanny_end_prefix_draws_without_an_extra_mana_condition_or_old_discount(self):
        cid = recipe(NANNY, LOOT); g = self.game((BEAST,), (cid,), mana=0)
        g.apply(EndTurn(1)); self.assertEqual(self.count(g), 1); self.assertEqual(self.price(g, BEAST), 4)

    def test_l_random_physical_discount_wait_restores_rolls_back_and_survives_source_death(self):
        cid = recipe(NANNY); g = self.game((BEAST, BEAST), (cid, WATCH)); g.apply(EndTurn(1))
        reader = self.portable(g); saved = g.snapshot(); rng = saved['rng_state']
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.pick(g, 'depart'); self.pick(reader, 'depart')
        self.assertEqual(g.snapshot(), reader.snapshot()); self.assertEqual(g.snapshot()['rng_state'], rng)
        prices = [quote_unselected_cost(g.state, g.registry, g.state.entities[i]).amount
            for i in g.state.players[1].hand if g.state.entities[i].card_id == BEAST]
        self.assertEqual(sorted(prices), [3, 4]); self.assertEqual(self.count(g, cid, zone='board'), 0)

    def test_m_unknown_current_hand_tribe_rolls_back_whole_end_and_randomness(self):
        g = self.game((BEAST, UNKNOWN), (recipe(NANNY),)); old = g.snapshot()
        with self.assertRaises((ValueError, ResolutionError)): g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), old)

    def test_n_real_shaper_keeps_entry_primary_and_selected_full_independent_death_body(self):
        cid = recipe(NANNY, LOOT, 'top'); g = self.game((SHAPER, BEAST, KILL), mode='offer')
        source = self.play(g, SHAPER); self.portable(g, 'offer')
        q = g.state.pending_choice; self.pick(g, next(o.id for o in q.options if o.card_id == cid))
        mana = g.state.players[1].mana; assembled = self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana-2)
        self.assertIn(source, g.state.players[1].board); self.play(g, KILL, assembled)
        self.assertEqual(self.price(g, BEAST), 3); self.portable(g, 'offer')

    def test_o_exact_original_bridge_clock_and_native_query_drift_are_rejected(self):
        r = fixture(); t = r.assemble_templates[NANNY]
        for changed in (replace(t, original_end_turn_id='cards.conditions.unused_mana_draw'),
                        replace(t, prefix=replace(t.prefix, end_turn=EndTurnSpec('either')))):
            with self.assertRaises(ValueError): validate_template(r, changed)
        with self.assertRaises(ValueError): replace(t, prefix=AssemblePrefix('battlecry'))
        with patch.object(cards, 'QUERY', PoolQuery(tribes_any=('dragon',))):
            with self.assertRaises(TargetValidationError): cards.load_batch()
        broken = fixture.__wrapped__(); broken._cards[NANNY] = replace(broken.card(NANNY), health=4)
        with self.assertRaises(TargetValidationError): cards.register_assemble_owner_hand_cost_followups(broken)
        source = r.assemble_native_end_conditions[cards.CONDITION]
        with self.assertRaises(TypeError): r.assemble_native_end_conditions['x'] = source
        with self.assertRaises(ValueError): r.register_assemble_native_end_condition(source)
        missing = fixture.__wrapped__(); missing._assemble_native_end_conditions.clear()
        with self.assertRaises(ValueError): recipe_options(missing, TRADER, LOOT)

    def test_p_silenced_current_copy_stays_silent_base_copy_restores_new_printed_end_body(self):
        cid = recipe(NANNY, LOOT); g = self.game((MUTE, COPY, BASE_COPY), (cid,))
        source = self.eid(g, cid, 'board'); self.play(g, MUTE, source)
        self.play(g, COPY, source); self.play(g, BASE_COPY, source); g.apply(EndTurn(1))
        self.assertEqual(self.count(g), 1)

    def test_q_empty_hand_candidate_set_has_no_random_draw_or_other_zone_discount(self):
        g = self.game((), (recipe(NANNY),), (BEAST,), deck=(BEAST,) * 8)
        rng = g.snapshot()['rng_state']; g.apply(EndTurn(1))
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(self.price(g, BEAST, 2), 4); self.assertEqual(self.price(g, BEAST, zone='deck'), 4)


if __name__ == '__main__':
    unittest.main()
