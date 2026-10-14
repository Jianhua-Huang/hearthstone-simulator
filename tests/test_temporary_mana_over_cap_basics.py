"""Independent temporary mana account, exercised through original public paths."""
from copy import deepcopy
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction,
    PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import (ChangeManaCrystals, ChoiceOption, GainArmor,
    GainTemporaryMana, RefreshMana, RequestChoice, SetManaCap, UnlockOverload)
from hs_sim.engine.paid_hand_acceptance import FinishPaidHandAcceptance, validate_queue
from hs_sim.engine.payment_projection import project_payment
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


def registry():
    r = Registry('temporary-mana-over-cap-tests-v1')
    r.register_card(CardDefinition('tm.hero', 'Finite account hero', CardType.HERO, health=30))
    r.register_card(CardDefinition('tm.filler', 'Finite draw filler', CardType.MINION, health=1))
    def fail(c):
        raise ResolutionError('Deliberate temporary mana continuation failure')
    r.register_behavior('tm.fail', fail)
    from hs_sim.engine.effects import InvokeBehavior
    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),
            ChoiceOption('fail', 'Fail', (GainArmor(c.player_id, 9),
                InvokeBehavior('tm.fail', c.source_id, c.player_id))),
        ), c.source_id),)
    operations = {
        'gain1': lambda c: (GainTemporaryMana(c.player_id, 1),),
        'gain5': lambda c: (GainTemporaryMana(c.player_id, 5),),
        'zero': lambda c: (GainTemporaryMana(c.player_id, 0),),
        'refresh': lambda c: (RefreshMana(c.player_id, 20),),
        'unlock': lambda c: (UnlockOverload(c.player_id, clear_pending=False),),
        'grow.empty': lambda c: (ChangeManaCrystals(c.player_id, 5),),
        'grow.full': lambda c: (ChangeManaCrystals(c.player_id, 5, filled=True),),
        'remove': lambda c: (ChangeManaCrystals(c.player_id, -3),),
        'cap': lambda c: (SetManaCap(c.player_id, 3),),
        'gain.wait': lambda c: (GainTemporaryMana(c.player_id, 5), *wait(c)),
        'gain.fail': lambda c: (GainTemporaryMana(c.player_id, 5),
            InvokeBehavior('tm.fail', c.source_id, c.player_id)),
        'paid': lambda c: (GainArmor(c.player_id, 2),),
        'expensive': lambda c: (GainArmor(c.player_id, 2),),
        'wait': wait,
    }
    for name, body in operations.items():
        cid = 'tm.' + name
        r.register_behavior(cid, body)
        cost = 11 if name == 'expensive' else 2 if name in ('paid', 'wait') else 0
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=cid))
    r.register_behavior('tm.wait.minion', wait)
    r.register_card(CardDefinition('tm.wait.minion', 'Finite paid acceptance probe',
        CardType.MINION, cost=2, health=2, battlecry='tm.wait.minion'))
    r.register_card(CardDefinition('tm.power', 'Finite mana payment probe',
        CardType.HERO_POWER, cost=11, on_use='tm.expensive'))
    def ending(c):
        if c.event.player_id != c.player_id: return ()
        return wait(c)
    r.register_behavior('tm.ending', ending)
    r.register_card(CardDefinition('tm.ending', 'Original end boundary probe',
        CardType.MINION, health=1, triggers=(TriggerSpec('turn_ended', 'tm.ending'),)))
    return r


class TemporaryManaOverCapTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy_hand=(), **setup):
        defaults = dict(max_mana=10, mana=10, deck=('tm.filler',) * 4)
        defaults.update(setup)
        return Game.from_scenario(Scenario((
            PlayerSetup('tm.hero', hand=tuple('tm.' + c for c in hand),
                board=tuple('tm.' + c for c in board), **defaults),
            PlayerSetup('tm.hero', hand=tuple('tm.' + c for c in enemy_hand),
                deck=('tm.filler',) * 4, max_mana=10, mana=10),
        ), seed=23), registry())

    def card(self, g, name, player=1):
        return next(i for i in g.state.players[player].hand
            if g.state.entities[i].card_id == 'tm.' + name)

    def play(self, g, name, player=1):
        g.apply(PlayCard(player, self.card(g, name, player)))

    def account(self, g, player=1):
        p = g.state.players[player]
        return p.mana, p.max_mana, p.mana_cap, p.temporary_mana, p.mana_spent

    def choose(self, g, option='ok'):
        p = g.state.pending_choice
        g.apply(SelectChoice(p.player_id, p.id, (option,)))

    def portable(self, g):
        original = g.snapshot()
        copies = (Game.from_snapshot(original, registry()), g.clone(), replay(build_replay(g), registry()))
        for candidate in copies: self.assertEqual(candidate.snapshot(), original)
        return copies

    def test_base_and_modified_growth_caps_allow_independent_temporary_account(self):
        for cap in (10, 11, 20):
            with self.subTest(cap=cap):
                g = self.game(('gain5',), max_mana=cap, mana=cap, mana_cap=cap)
                self.play(g, 'gain5')
                self.assertEqual(self.account(g), (cap+5, cap, cap, 5, 0))
                event = next(e for e in reversed(g.events) if e.kind == 'mana_changed')
                self.assertEqual(event.amount, 5)

    def test_stacked_gains_and_zero_gain_do_not_consume_rng_or_change_crystals(self):
        g = self.game(('gain5', 'gain1', 'zero')); rng = g._rng.getstate()
        for name in ('gain5', 'gain1', 'zero'): self.play(g, name)
        self.assertEqual(self.account(g), (16, 10, 10, 6, 0))
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_balanced_initial_above_cap_state_restores_without_clipping(self):
        g = self.game(temporary_mana=5, mana=15)
        self.assertEqual(self.account(g), (15, 10, 10, 5, 0))
        self.portable(g)

    def test_permanent_growth_is_still_capped_without_discarding_temporary_mana(self):
        for name in ('grow.empty', 'grow.full'):
            with self.subTest(name=name):
                g = self.game((name,), temporary_mana=4, mana=14)
                self.play(g, name)
                self.assertEqual(self.account(g), (14, 10, 10, 4, 0))

    def test_empty_and_filled_growth_below_cap_preserve_temporary_account(self):
        for name, amount, spent in (('grow.empty', 12, 5), ('grow.full', 17, 0)):
            with self.subTest(name=name):
                g = self.game((name,), max_mana=8, mana=12, mana_cap=20, temporary_mana=4)
                self.play(g, name)
                self.assertEqual(self.account(g), (amount, 13, 20, 4, spent))

    def test_refresh_keeps_unspent_temporary_mana_and_only_restores_permanent_spend(self):
        g = self.game(('refresh',), temporary_mana=5, mana=12)
        self.play(g, 'refresh')
        self.assertEqual(self.account(g), (15, 10, 10, 5, 0))
        self.portable(g)

    def test_unlock_keeps_unspent_temporary_mana_and_pending_overload_policy(self):
        g = self.game(('unlock',), temporary_mana=5, mana=12, overload_locked=3, overload_owed=2)
        self.play(g, 'unlock')
        self.assertEqual(self.account(g), (15, 10, 10, 5, 0))
        self.assertEqual((g.state.players[1].overload_locked, g.state.players[1].overload_owed), (0, 2))
        self.portable(g)

    def test_crystal_removal_and_cap_reduction_preserve_unused_temporary_account(self):
        for name, expected in (('remove', (12, 7, 10, 5, 0)), ('cap', (8, 3, 3, 5, 0))):
            with self.subTest(name=name):
                g = self.game((name,), temporary_mana=5, mana=15)
                self.play(g, name); self.assertEqual(self.account(g), expected)

    def test_original_payment_projection_spends_temporary_first_above_cap(self):
        g = self.game(('expensive',), temporary_mana=5, mana=15)
        source = self.card(g, 'expensive'); quote = g.quote_cost(source)
        saved = g.snapshot(); result = project_payment(g.state, quote, cause_reason='PlayFromHand')
        self.assertEqual(g.snapshot(), saved)
        p = result.final_state.players[1]
        self.assertEqual((p.mana, p.temporary_mana, p.mana_spent), (4, 0, 6))
        g.apply(PlayCard(1, source)); self.assertEqual(self.account(g), (4, 10, 10, 0, 6))
        self.assertEqual(sum(e.amount for e in g.events if e.kind == 'mana_spent'), 11)
        self.portable(g)

    def test_partial_temporary_payment_does_not_spend_permanent_crystals(self):
        g = self.game(('paid',), temporary_mana=5, mana=15)
        self.play(g, 'paid'); self.assertEqual(self.account(g), (13, 10, 10, 3, 0))

    def test_player_legal_actions_and_submission_share_above_cap_affordability(self):
        g = self.game(('expensive',), temporary_mana=1, mana=11)
        source = self.card(g, 'expensive')
        self.assertIn(PlayCard(1, source), g.legal_actions())
        port = g.for_player(1); menu = port.legal_actions()
        command = next(a for a in menu['actions'] if a['type'] == 'play_card')
        result = port.submit({'revision': menu['revision'], 'action': command})
        self.assertTrue(result['accepted']); self.assertIsNone(result['error'])
        self.assertEqual(self.account(g), (0, 10, 10, 0, 10))

    def test_insufficient_above_cap_available_mana_still_rejects_and_rolls_back(self):
        g = self.game(('expensive',)); saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, 'expensive')
        self.assertEqual(g.snapshot(), saved)

    def test_hero_power_uses_the_same_above_cap_payment_account(self):
        g = self.game(hero_power_card_id='tm.power', temporary_mana=1, mana=11)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual(self.account(g), (0, 10, 10, 0, 10))
        self.portable(g)

    def test_temporary_amount_survives_end_reactions_and_expires_at_turn_handoff(self):
        g = self.game(board=('ending',), temporary_mana=5, mana=15)
        g.apply(EndTurn(1)); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.account(g), (15, 10, 10, 5, 0))
        copies = self.portable(g)
        for candidate in (g, *copies): self.choose(candidate)
        for candidate in copies: self.assertEqual(candidate.snapshot(), g.snapshot())
        self.assertEqual(self.account(g), (10, 10, 10, 0, 0))
        self.assertEqual(g.state.active_player, 2)

    def test_second_player_owns_gain_and_next_own_turn_replenishes_only_crystals(self):
        g = self.game(enemy_hand=('gain5',)); g.apply(EndTurn(1)); self.play(g, 'gain5', 2)
        self.assertEqual(self.account(g, 2), (15, 10, 10, 5, 0))
        self.assertEqual(self.account(g, 1), (10, 10, 10, 0, 0))
        g.apply(EndTurn(2)); g.apply(EndTurn(1))
        self.assertEqual(self.account(g, 2), (10, 10, 10, 0, 0))

    def test_gain_before_wait_roundtrips_and_failed_resume_preserves_complete_account(self):
        g = self.game(('gain.wait',)); self.play(g, 'gain.wait')
        self.assertEqual(self.account(g), (15, 10, 10, 5, 0)); saved = g.snapshot()
        copies = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        for candidate in (g, *copies): self.choose(candidate)
        for candidate in copies: self.assertEqual(candidate.snapshot(), g.snapshot())
        self.assertEqual(self.account(g), (15, 10, 10, 5, 0))

    def test_paid_spell_and_paid_hand_waits_keep_original_above_cap_proofs(self):
        for name in ('wait', 'wait.minion'):
            with self.subTest(name=name):
                g = self.game((name,), temporary_mana=5, mana=15); self.play(g, name)
                self.assertEqual(self.account(g), (13, 10, 10, 3, 0)); saved = g.snapshot()
                copies = self.portable(g)
                with self.assertRaises(ResolutionError): self.choose(g, 'fail')
                self.assertEqual(g.snapshot(), saved)
                for candidate in (g, *copies): self.choose(candidate)
                for candidate in copies: self.assertEqual(candidate.snapshot(), g.snapshot())
                self.assertEqual(self.account(g), (13, 10, 10, 3, 0))

    def test_mutated_paid_hand_original_account_is_rejected_even_if_balanced(self):
        g = self.game(('wait.minion',), temporary_mana=5, mana=15); self.play(g, 'wait.minion')
        queue = (*g._frame.prefix, *g._frame.continuation)
        tail = next(work for work in queue if type(work) is FinishPaidHandAcceptance)
        validate_queue(g._state, g.registry, queue, game=g)
        p = tail.proof.payment_state.players[1]; p.temporary_mana -= 1; p.mana -= 1
        with self.assertRaises(ValueError): validate_queue(g._state, g.registry, queue, game=g)

    def test_immediate_failed_gain_rolls_back_original_action_and_rng(self):
        g = self.game(('gain.fail',)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'gain.fail')
        self.assertEqual(g.snapshot(), saved)

    def test_invalid_account_cache_integer_and_crystal_cap_still_rejected(self):
        g = self.game(temporary_mana=5, mana=15)
        for key, value in (('mana', 14), ('temporary_mana', True),
                           ('mana_spent', 11), ('max_mana', 11), ('temporary_mana', -1)):
            snapshot = g.snapshot(); snapshot['state']['players']['1'][key] = value
            payload = g._hash_payload(); payload['state'] = snapshot['state']
            snapshot['state_hash'] = canonical_hash(payload)
            with self.subTest(key=key), self.assertRaises(SnapshotError):
                Game.from_snapshot(snapshot, registry())

    def test_old_account_semantics_are_rejected_without_new_wire_fields(self):
        g = self.game(temporary_mana=1, mana=11); current = g.snapshot()
        self.assertEqual((g.ruleset.id, g.mechanics.version, current['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, 265))
        for key in ('ruleset', 'mechanics_version'):
            old = deepcopy(current)
            if key == 'ruleset': old[key]['id'] = 'prototype-v247'
            else: old[key]['version'] = 'core-effects-v241'
            with self.subTest(key=key), self.assertRaises(SnapshotError):
                Game.from_snapshot(old, registry())

    def test_player_views_show_public_resource_amount_but_keep_internal_state_private(self):
        g = self.game(('gain.wait',)); self.play(g, 'gain.wait'); saved = g.snapshot()
        for viewer in (1, 2):
            view = g.observe(viewer)
            player = next(p for p in view['players'] if p['id'] == 1)
            self.assertEqual((player['mana'], player['max_mana'], player['mana_cap']), (15, 10, 10))
            self.assertNotIn('mana_spent', player)
            public = json.dumps(view) + json.dumps(g.player_events(viewer)) + json.dumps(g.for_player(viewer).legal_actions())
            for key in ('rng_state', 'resolution_frame', 'payment_state', 'submission_base'):
                self.assertNotIn('"' + key + '"', public)
        self.assertEqual(g.snapshot(), saved)


class ExistingCoinOverCapTests(unittest.TestCase):
    def test_existing_pinned_complete_coin_representation_uses_corrected_public_account(self):
        from hs_sim.engine.representative import build_registry
        r = build_registry()
        for cap in (10, 20):
            with self.subTest(cap=cap):
                g = Game.from_scenario(Scenario((
                    PlayerSetup('HERO_08', hand=('GAME_005',), max_mana=cap, mana=cap, mana_cap=cap),
                    PlayerSetup('HERO_01'),
                ), seed=71), r)
                coin = g.state.players[1].hand[0]; rng = g._rng.getstate()
                g.apply(PlayCard(1, coin)); p = g.state.players[1]
                self.assertEqual((p.mana, p.max_mana, p.mana_cap, p.temporary_mana), (cap+1, cap, cap, 1))
                self.assertEqual(g.state.entities[coin].zone, Zone.GRAVEYARD)
                self.assertEqual(g._rng.getstate(), rng)
                self.assertEqual(replay(build_replay(g), r).snapshot(), g.snapshot())
                self.assertEqual(Game.from_snapshot(g.snapshot(), r).snapshot(), g.snapshot())


if __name__ == '__main__':
    unittest.main()
