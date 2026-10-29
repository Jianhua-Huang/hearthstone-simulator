"""Real Varian/Vol'jin entries over original top-card and swap materials."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.cards import varian_voljin_dependencies as native
from hs_sim.engine import Game, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Destroy, GainArmor,
    InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand)
from hs_sim.engine.hand_history import hand_entry
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.minion_hand_swaps import SwapWithControllerHand
from hs_sim.engine.model import (CardDefinition, CardType, CastWhenDrawnSpec, CostSpec,
    Keyword, SummonQuantitySpec, TriggerSpec, Zone)
from hs_sim.engine.recruit_summons import RecruitTopMinionOrDraw
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import AddToDeck, CardReference
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest
from tools import card_batch as batch

VARIAN, VOLJIN = native.CARDS
P = 'k656.'
A, B, OTHER, SPELL, TRAP, WATCH, FAIL, GROW, STEAL, DOUBLE, STALE = (
    P + s for s in ('a', 'b', 'other', 'spell', 'trap', 'watch', 'fail', 'grow', 'steal', 'double', 'stale'))


@lru_cache(maxsize=None)
def host(role='writer'):
    return build_cn37_local_pool_format()


@lru_cache(maxsize=None)
def registry(mode='normal', role='writer'):
    r = opening_registry(); native.register_varian_voljin_dependencies(r)
    r.register_behavior(P + 'battlecry', lambda c: (GainArmor(c.player_id, 11),))
    r.register_behavior(SPELL, lambda c: (GainArmor(c.player_id, 1),))
    r.register_behavior(TRAP, lambda c: (GainArmor(c.player_id, 3),))

    def fail(c):
        raise ValueError('K656 intentional failure after actual native work')

    def grow(c):
        target = c.state.entities[c.target_id]
        incoming = next(c.state.entities[i] for i in c.state.players[target.controller].hand
            if c.state.entities[i].card_id == B)
        return (Buff(target.id, 4, 5, c.source_id), BuffStoredCard(CardReference.capture(incoming), 2, 3, c.source_id,
            cost=CostSpec(delta=-1)))

    def stale(c):
        target = c.state.entities[c.target_id]
        request = SwapWithControllerHand(MinionReference.capture(target), SummonCause.capture(c))
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue', (request,)),
            ChoiceOption('remove', 'Return original target', (ReturnToHand(target.id), request))),
            c.source_id),)

    def watch(c):
        event = c.event; target = c.state.entities.get(event.target_id)
        if mode == 'swap_fail' and event.kind == 'card_returned':
            root = c.state.card_summon_history[-1]; incoming = root.deliveries[0].entity
            if incoming.entity_id not in c.state.players[incoming.controller].board:
                raise ValueError('Swap failed before committing its actual incoming entity')
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if mode == 'varian_remove' and event.kind == 'minion_summoned' and target is not None and target.card_id == A:
            source = next(e for e in c.state.entities.values() if e.card_id == VARIAN and e.zone == Zone.BOARD)
            return (Destroy(source.id, c.source_id),)
        if mode == 'varian_inject' and event.kind == 'minion_summoned' and target is not None and target.card_id == A:
            return (AddToDeck(1, OTHER, position='top', source_id=c.source_id),)
        waiting = (mode == 'swap_wait' and event.kind == 'card_returned' or
            mode == 'varian_wait' and event.kind == 'minion_summoned' and target is not None and target.card_id == A)
        if not waiting:
            return ()
        if mode == 'swap_wait':
            root = c.state.card_summon_history[-1]; incoming = root.deliveries[0].entity
            if (target.zone != Zone.HAND or target.id in c.state.players[target.controller].board or
                    incoming.entity_id not in c.state.players[incoming.controller].board):
                raise ValueError('Swap published a partial allocation')
        return (RequestChoice(1, (ChoiceOption('continue', 'Continue'), ChoiceOption('fail', 'Fail', (
            RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), InvokeBehavior(FAIL, c.source_id, 1)))),
            c.source_id, prompt='Original physical entry notification'),)

    for name, body in ((FAIL, fail), (GROW, grow), (STEAL, lambda c: (ChangeControl(c.target_id, 1),)),
            (STALE, stale), (WATCH, watch)):
        r.register_behavior(name, body)
    for cid, attack, health in ((A, 2, 3), (B, 5, 7), (OTHER, 3, 4)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=attack, health=health,
            on_play=P + 'battlecry', metadata=metadata()))
    r.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL, cost=1, on_play=SPELL, metadata=metadata()))
    r.register_card(CardDefinition(TRAP, TRAP, CardType.SPELL, cost=1, on_play=TRAP,
        keywords=(Keyword.CASTS_WHEN_DRAWN,), cast_when_drawn=CastWhenDrawnSpec(), metadata=metadata(collectible=False)))
    for cid in (GROW, STEAL):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, requires_target=True, metadata=metadata()))
    r.register_card(CardDefinition(STALE, STALE, CardType.MINION, health=2, on_play=STALE,
        requires_target=True, metadata=metadata()))
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30, metadata=metadata(),
        triggers=(TriggerSpec('minion_summoned', WATCH), TriggerSpec('card_returned', WATCH))))
    r.register_card(CardDefinition(DOUBLE, DOUBLE, CardType.MINION, health=3, metadata=metadata(),
        summon_quantities=(SummonQuantitySpec(),)))
    return r


def rehash(snapshot):
    keys = ('ruleset', 'registry_fingerprint', 'mechanics_version', 'state', 'rng_state',
        'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information')
    snapshot['state_hash'] = canonical_digest({k: snapshot[k] for k in keys})
    return snapshot


class VarianVoljinDependenciesTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(registry)

    def game(self, *, hand=(), board=(), enemy=(), enemy_hand=(), deck=('card.40',) * 6, mode='normal', limit=7):
        self.mode = mode
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=hand, board=board,
            deck=deck, mana=60, max_mana=60, mana_cap=60),
            PlayerSetup('warrior.hero', board=enemy, hand=enemy_hand, deck=('card.39',) * 6)), seed=656),
            registry(mode), ruleset=Ruleset(max_board=limit))

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def assert_private(self, g, player, hidden=()):
        for data in (g.for_player(player).observe(), g.player_events(player)):
            text = json.dumps(data, default=str)
            for value in (*hidden, 'swap_with_controller_hand', 'rng_state', 'resolution_frame', 'zone_epoch', 'hand_entry_id'):
                self.assertNotIn(value, text)

    def test_complete_original_rows_and_primary_faces_define_exact_two_native_identities(self):
        d = native.load_batch(); r = registry()
        self.assertEqual(len(d['cards']), 2); self.assertEqual(len(d['official_observations']), 4)
        for row in d['cards']:
            raw = row['record']; card = r.card(raw['id'])
            self.assertEqual(canonical_digest(asdict(card)), row['definition_sha256'])
            self.assertEqual((card.cost, card.attack, card.health), (raw['cost'], raw['attack'], raw['health']))
        for o in d['official_observations']:
            row = next(v['record'] for v in d['cards'] if v['record']['id'] == o['card_id'])
            batch.check_face(row, o['face'], o['locale'])

    def test_real_local_host_runs_both_actual_entries_with_physical_originals_and_one_payment_each(self):
        f = host(); g = Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=(VARIAN, VOLJIN, 'CORE_CS2_182'),
            deck=('CORE_CS2_182',) * 3, mana=60, max_mana=60, mana_cap=60), PlayerSetup('HERO_08')),
            seed=656, generation_context=f.context), f.registry)
        hand_partner = g.state.players[1].hand[-1]; source = self.play(g, VARIAN)
        target = next(i for i in g.state.players[1].board if i != source)
        self.play(g, VOLJIN, target)
        self.assertIn(target, g.state.players[1].hand); self.assertIn(hand_partner, g.state.players[1].board)
        self.assertEqual(g.state.players[1].mana, 45); self.assertEqual(len(g.state.play_history), 2)
        self.assertEqual(len(g.state.card_summon_history), 4)
        self.assertTrue(set(native.CARDS).isdisjoint(f.root_card_ids)); self.assertNotIn('WON_113', f.registry.cards)
        saved = g.snapshot(); reader = host('reader').registry
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)

    def test_varian_three_original_slots_direct_minions_and_normal_spell_draw_without_battlecries(self):
        g = self.game(hand=(VARIAN,), deck=(A, SPELL, B))
        originals = tuple(g.state.players[1].deck); source = self.play(g, VARIAN)
        self.assertEqual(g.state.players[1].board, [source, originals[0], originals[2]])
        self.assertEqual(g.state.players[1].hand, [originals[1]])
        self.assertEqual(self.armor(g), 0); self.assertEqual(g.state.players[1].mana, 50)
        self.assertEqual(len(g.state.draw_history), 1); self.assertEqual(len(g.state.play_history), 1)
        self.portable(g)

    def test_varian_direct_entries_bypass_full_hand_and_do_not_emit_hand_draws(self):
        g = self.game(hand=(VARIAN,) + (SPELL,) * 9, deck=(A, SPELL, B))
        originals = tuple(g.state.players[1].deck); self.play(g, VARIAN)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertTrue(all(i in g.state.players[1].board for i in (originals[0], originals[2])))
        self.assertTrue(all(g.state.entities[i].zone != Zone.GRAVEYARD for i in originals))
        self.assertEqual(len(g.state.draw_history), 1); self.assertEqual(self.armor(g), 0)

    def test_varian_full_board_falls_back_to_three_normal_hand_draws(self):
        g = self.game(hand=(VARIAN,), board=('card.1',) * 6, deck=(A, B, SPELL))
        originals = tuple(g.state.players[1].deck); self.play(g, VARIAN)
        self.assertEqual(tuple(g.state.players[1].hand), originals)
        self.assertEqual(len(g.state.draw_history), 3); self.assertFalse(g.state.card_summon_history)
        self.assertEqual(len(g.state.players[1].board), 7); self.assertEqual(self.armor(g), 0)

    def test_varian_uses_actual_custom_capacity_and_burns_only_ordinary_full_hand_draws(self):
        g = self.game(hand=(VARIAN,) + (SPELL,) * 9, deck=(A, B, SPELL), limit=2)
        originals = tuple(g.state.players[1].deck); self.play(g, VARIAN)
        self.assertIn(originals[0], g.state.players[1].board)
        self.assertIn(originals[1], g.state.players[1].hand)
        self.assertEqual(g.state.entities[originals[2]].zone, Zone.GRAVEYARD)
        self.assertEqual((len(g.state.players[1].board), len(g.state.players[1].hand)), (2, 10))

    def test_varian_cast_when_drawn_replacement_minion_is_not_one_of_its_direct_entry_slots(self):
        g = self.game(hand=(VARIAN,), deck=(TRAP, A, B, SPELL))
        trap, replacement, direct, spell = g.state.players[1].deck; self.play(g, VARIAN)
        self.assertIn(replacement, g.state.players[1].hand); self.assertIn(direct, g.state.players[1].board)
        self.assertIn(spell, g.state.players[1].hand); self.assertEqual(g.state.entities[trap].zone, Zone.GRAVEYARD)
        self.assertEqual(self.armor(g), 3); self.assertEqual(len(g.state.card_summon_history), 1)
        self.portable(g)

    def test_varian_empty_deck_resolves_three_normal_fatigue_draws(self):
        g = self.game(hand=(VARIAN,), deck=()); self.play(g, VARIAN)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 24)
        self.assertFalse(g.state.card_summon_history)

    def test_varian_wait_between_slots_restores_remaining_original_route_work_and_rng(self):
        g = self.game(hand=(VARIAN,), board=(WATCH,), deck=(A, SPELL, B), mode='varian_wait')
        self.play(g, VARIAN); self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K656 intentional failure'):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g); self.choose(restored); self.assertEqual(g.snapshot(), restored.snapshot())
        self.portable(g); self.assertEqual(len(g.state.players[1].board), 4)

    def test_varian_later_slots_continue_after_original_source_dies(self):
        g = self.game(hand=(VARIAN,), board=(WATCH,), deck=(A, SPELL, B), mode='varian_remove')
        source = self.play(g, VARIAN)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertIn(B, [g.state.entities[i].card_id for i in g.state.players[1].board])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [SPELL]); self.portable(g)

    def test_varian_later_slot_requeries_actual_top_after_previous_entry_reactions(self):
        g = self.game(hand=(VARIAN,), board=(WATCH,), deck=(A, B, SPELL), mode='varian_inject')
        self.play(g, VARIAN)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [WATCH, VARIAN, A, OTHER, B])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [SPELL])

    def test_voljin_friendly_target_swaps_two_originals_in_its_own_hand_without_extra_battlecry(self):
        g = self.game(hand=(VOLJIN, B), board=(A,))
        target = g.state.players[1].board[0]; incoming = g.state.players[1].hand[-1]
        source = self.play(g, VOLJIN, target)
        self.assertEqual(g.state.players[1].board, [incoming, source]); self.assertEqual(g.state.players[1].hand, [target])
        self.assertEqual(self.armor(g), 0); self.assertEqual(g.state.players[1].mana, 55)
        self.assertEqual(hand_entry(g.state, g.state.entities[target].hand_entry_id).source_id, source)
        self.portable(g)

    def test_voljin_enemy_full_board_and_full_hand_reuse_both_original_slots(self):
        g = self.game(hand=(VOLJIN,), enemy=('card.1', A, 'card.2') + ('card.3',) * 4, enemy_hand=(B,) + (SPELL,) * 9)
        target = g.state.players[2].board[1]; incoming = g.state.players[2].hand[0]
        source = self.play(g, VOLJIN, target)
        self.assertEqual(g.state.players[2].board[1], incoming)
        self.assertEqual((len(g.state.players[2].board), len(g.state.players[2].hand)), (7, 10))
        self.assertIn(target, g.state.players[2].hand)
        self.assertEqual((g.state.entities[target].owner, g.state.entities[incoming].owner), (2, 2))
        self.assertEqual(hand_entry(g.state, g.state.entities[target].hand_entry_id).source_id, source)
        self.assertEqual(self.armor(g, 2), 0); self.portable(g)

    def test_voljin_uses_current_controller_hand_after_control_change_and_keeps_original_owner(self):
        g = self.game(hand=(STEAL, VOLJIN, B), enemy=(A,), enemy_hand=(OTHER,))
        target = g.state.players[2].board[0]; incoming = g.state.players[1].hand[-1]
        self.play(g, STEAL, target); self.play(g, VOLJIN, target)
        self.assertIn(target, g.state.players[1].hand); self.assertIn(incoming, g.state.players[1].board)
        self.assertEqual(g.state.entities[target].owner, 2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].hand], [OTHER])

    def test_voljin_no_eligible_hand_minion_keeps_target_and_random_state(self):
        for hand in ((), (SPELL,)):
            g = self.game(hand=(VOLJIN,), enemy=(A,), enemy_hand=hand)
            target = g.state.players[2].board[0]; rng = g._rng.getstate(); self.play(g, VOLJIN, target)
            self.assertIn(target, g.state.players[2].board); self.assertEqual(g._rng.getstate(), rng)
            self.assertFalse(g.state.card_summon_history)

    def test_voljin_empty_board_allows_untargeted_entry_but_never_targets_a_hero(self):
        g = self.game(hand=(VOLJIN,)); self.play(g, VOLJIN)
        self.assertFalse(g.state.card_summon_history)
        g = self.game(hand=(VOLJIN,)); saved = g.snapshot()
        with self.assertRaises(ValueError):
            self.play(g, VOLJIN, g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(), saved)

    def test_voljin_same_name_physical_candidates_keep_independent_equal_weights(self):
        g = self.game(hand=(VOLJIN,), enemy=(A,), enemy_hand=(B, B))
        candidates = tuple(g.state.players[2].hand); rng = Random(); rng.setstate(g._rng.getstate())
        expected = rng.choice(candidates); self.play(g, VOLJIN, g.state.players[2].board[0])
        self.assertIn(expected, g.state.players[2].board); self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual(g.state.card_summon_history[-1].request.materials[0].reference.entity_id, expected)

    def test_voljin_incoming_stored_buffs_survive_outgoing_active_buffs_reset(self):
        g = self.game(hand=(GROW, VOLJIN), enemy=(A,), enemy_hand=(B,))
        target = g.state.players[2].board[0]; incoming = g.state.players[2].hand[0]
        self.play(g, GROW, target); self.play(g, VOLJIN, target)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (2, 3))
        self.assertEqual((g.state.entities[incoming].attack, g.state.entities[incoming].health), (7, 10))
        self.portable(g)

    def test_voljin_wait_after_atomic_swap_restores_full_allocations_and_hides_other_candidates(self):
        g = self.game(hand=(VOLJIN,), board=(WATCH,), enemy=(A,), enemy_hand=(B, OTHER), mode='swap_wait')
        self.play(g, VOLJIN, g.state.players[2].board[0]); self.assertIsNotNone(g.state.pending_choice)
        chosen = g.state.card_summon_history[-1].request.materials[0].card_id
        hidden = OTHER if chosen == B else B
        restored = self.portable(g); self.assert_private(g, 1, (hidden,))
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K656 intentional failure'):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g); self.assert_private(g, 1, (hidden,))

    def test_voljin_exception_after_actual_random_entry_rolls_back_payment_both_entities_and_rng(self):
        g = self.game(hand=(VOLJIN,), board=(WATCH,), enemy=(A,), enemy_hand=(B, OTHER), mode='swap_fail')
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K656 intentional failure'):
            self.play(g, VOLJIN, g.state.players[2].board[0])
        self.assertEqual(g.snapshot(), saved)

    def test_controller_hand_quantity_returns_original_once_and_allocates_only_extra_copy(self):
        g = self.game(hand=(VOLJIN,), board=(DOUBLE,), enemy=(A,), enemy_hand=(B,))
        target = g.state.players[2].board[0]; incoming = g.state.players[2].hand[0]
        self.play(g, VOLJIN, target)
        self.assertEqual(len(g.state.players[2].board), 2); self.assertIn(incoming, g.state.players[2].board)
        self.assertEqual(g.state.players[2].hand, [target])
        self.assertEqual(sum(e.kind == 'card_returned' for e in g.events), 1); self.portable(g)

    def test_departed_original_target_does_not_swap_a_new_residence_or_consume_random(self):
        g = self.game(hand=(STALE,), enemy=(A,), enemy_hand=(B,))
        target = g.state.players[2].board[0]; self.play(g, STALE, target); rng = g._rng.getstate()
        self.portable(g); self.choose(g, 'remove')
        self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.card_summon_history)
        self.assertIn(target, g.state.players[2].hand)

    def test_rehashed_saved_swap_mode_cannot_borrow_old_source_rule_or_nonboolean_flag(self):
        g = self.game(hand=(VOLJIN,), board=(WATCH,), enemy=(A,), enemy_hand=(B,), mode='swap_wait')
        self.play(g, VOLJIN, g.state.players[2].board[0]); self.assertIsNotNone(g.state.pending_choice)
        for value in (False, 'true'):
            saved = deepcopy(g.snapshot())
            saved['state']['card_summon_history'][-1]['request']['materials'][0]['swap_with_controller_hand'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                Game.from_snapshot(rehash(saved), registry('swap_wait', 'independent-reader'))

    def test_rehashed_waiting_varian_slot_cannot_switch_recipient_player(self):
        g = self.game(hand=(VARIAN,), board=(WATCH,), deck=(A, SPELL, B), mode='varian_wait'); self.play(g, VARIAN)
        saved = deepcopy(g.snapshot()); found = []
        def visit(node):
            if isinstance(node, dict):
                if node.get('type') == 'hs_sim.engine.recruit_summons.RecruitTopMinionOrDraw':
                    found.append(node)
                for item in node.values():
                    visit(item)
            elif isinstance(node, list):
                for item in node:
                    visit(item)
        visit(saved['resolution_frame']); self.assertTrue(found)
        found[0]['fields']['player_id'] = 2
        with self.assertRaises(ValueError):
            Game.from_snapshot(rehash(saved), registry('varian_wait', 'independent-reader'))

    def test_new_public_scopes_reject_malformed_sources_and_old_snapshot_schema(self):
        g = self.game(hand=(VARIAN,), board=(A,), enemy=(B,), enemy_hand=(A,))
        saved = g.snapshot(); saved['schema_version'] = 630
        with self.assertRaisesRegex(ValueError, 'schema'):
            Game.from_snapshot(rehash(saved), registry())
        with self.assertRaises(ValueError):
            SummonStoredCard(CardReference.capture(g.state.entities[g.state.players[2].hand[0]]), 2,
                swap_with_controller_hand=True)
        self.play(g, VARIAN); root = g.state.card_summon_history[-1]; cause = root.request.cause
        with self.assertRaises(ValueError):
            RecruitTopMinionOrDraw(2, cause)
        with self.assertRaises(ValueError):
            SwapWithControllerHand(MinionReference.capture(g.state.entities[g.state.players[2].board[0]]),
                replace(cause, origin='hero_power'))


if __name__ == '__main__':
    unittest.main()
