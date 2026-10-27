"""Original Arcane cards use ordinary discards, group transforms and pool entries."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, past_arcane_board_replacements as native
from hs_sim.cards.plucky_podling_card import CARD as PODLING
from hs_sim.engine import (AuraSpec, CardDefinition, CardType, CastSpell, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, GainArmor, GainTemporaryMana,
    InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.model import CostSpec, DamageKind, SummonQuantitySpec
from hs_sim.engine.named_transform_groups import TransformMinionsToCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import GrantSummonQuantity
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

COMMUNION, MASS, CALL = native.LEAVES
EXCESS, SHEEP, TWIN = native.TOKENS
P = 'k596.'
HERO, WATCH_HERO, UNIT, SECOND, ADDED, AURA, FRAGILE, DORMANT, LOCATION, QUANTITY, PREP, TEMP, AUTO, FAULT, BAD_BATCH, COST = (
    P+x for x in ('hero', 'watch_hero', 'unit', 'second', 'added', 'aura', 'fragile', 'dormant', 'location',
        'quantity', 'prep', 'temp', 'auto', 'fault', 'bad_batch', 'cost'))


@lru_cache(None)
def host(role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    def fault(c): raise ResolutionError('K596 deliberate continuation failure')
    def target(c, cid, player=None):
        return next(c.state.entities[i] for i in c.state.players[c.player_id if player is None else player].board
            if c.state.entities[i].card_id == cid)
    def watch(c):
        event = c.event; cast = c.state.cast_history[-1] if c.state.cast_history else None
        source = c.state.entities.get(event.source_id)
        options = (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fault', 'Late failure', (InvokeBehavior(FAULT, c.source_id, c.player_id),)))
        if (event.kind == 'card_discarded' and source is not None and source.card_id == COMMUNION and
                event.player_id == c.player_id and len(c.state.discard_history) == 1):
            second = next((c.state.entities[i] for i in c.state.players[c.player_id].hand
                if c.state.entities[i].card_id == SECOND), None)
            if second is not None:
                options += (ChoiceOption('move', 'Move queued second original',
                    (MoveCard(CardReference.capture(second), c.player_id, Zone.DECK, source_id=c.source_id),)),)
            return (AddToHand(c.player_id, ADDED, c.source_id), RequestChoice(c.player_id, options, c.source_id))
        if event.kind == 'transformed' and cast is not None and cast.card_id == MASS and not cast.completed:
            active = [c.state.entities[i] for player in (1, 2) for i in c.state.players[player].board
                if c.state.entities[i].kind == CardType.MINION and c.state.entities[i].active]
            if any(e.card_id != SHEEP for e in active): raise ResolutionError('Original group was not fully transformed before its first notice')
            return (GainArmor(c.player_id, 1),) + ((RequestChoice(c.player_id, options, c.source_id),)
                if dict(event.data).get('old_card_id') == AURA else ())
        root = c.state.card_summon_history[-1] if c.state.card_summon_history else None
        if (event.kind == 'minion_summoned' and root is not None and root.request.cause is not None and
                root.request.cause.source.card_id in (CALL, TWIN) and root.request.cause.player_id == c.player_id and
                len(c.state.card_summon_history) == 1):
            q = next((c.state.entities[i] for i in c.state.players[c.player_id].board
                if c.state.entities[i].card_id == QUANTITY), None)
            if q is not None:
                options += (ChoiceOption('double', 'Later quantity source',
                    (GrantSummonQuantity(q.id, SummonQuantitySpec(2), c.source_id),)),)
            return (RequestChoice(c.player_id, options, c.source_id),)
        return ()
    def prep(c):
        return (Damage(target(c, FRAGILE).id, 1, c.source_id, DamageKind.EFFECT),)
    def auto(c):
        return (CastSpell(c.player_id, CALL, c.source_id),)
    def bad_batch(c):
        refs = tuple(MinionReference.capture(c.state.entities[i]) for i in c.state.players[c.player_id].board)
        return (TransformMinionsToCard(refs, 'missing.k596', c.source_id),)
    def cost(c):
        return (ModifyCost(c.state.players[c.player_id].board[0], CostSpec(set_to=1), c.source_id),)
    for cid, body in ((FAULT, fault), (PREP, prep), (TEMP, lambda c:(GainTemporaryMana(c.player_id, 10),)),
            (AUTO, auto), (BAD_BATCH, bad_batch), (COST, cost), (P+'death', lambda c:(GainArmor(c.player_id, 99),))): r.register_behavior(cid, body)
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100))
    r.register_card(CardDefinition(WATCH_HERO, WATCH_HERO, CardType.HERO, health=100, triggers=tuple(
        TriggerSpec(event, P+'watch') for event in ('card_discarded', 'transformed', 'minion_summoned'))))
    for cid in (UNIT, SECOND, ADDED, FRAGILE, QUANTITY):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=0, attack=1, health=1,
            deathrattle=P+'death' if cid == SECOND else None,
            keywords=(Keyword.STEALTH, Keyword.ELUSIVE) if cid == FRAGILE else ()))
    r.register_card(CardDefinition(AURA, AURA, CardType.MINION, cost=0, health=1, auras=(AuraSpec(health=1, include_self=False),)))
    r.register_card(CardDefinition(DORMANT, DORMANT, CardType.MINION, cost=0, health=3, dormant_turns=2))
    r.register_card(CardDefinition(LOCATION, LOCATION, CardType.LOCATION, durability=3, on_use=FAULT))
    for cid in (PREP, TEMP, AUTO, BAD_BATCH, COST):r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    return f


class PastArcaneBoardReplacementTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role:host(role).registry)

    def game(self, hand=(), *, own=(), enemy=(), deck=(), player=1, watch=False, maximum=20, available=None, cap=20):
        f = host(); setups = tuple(PlayerSetup(WATCH_HERO if p == player and watch else HERO,
            hand=hand if p == player else (), board=own if p == player else enemy,
            deck=deck if p == player else (UNIT,)*5, mana=maximum if available is None else available,
            max_mana=maximum, mana_cap=cap) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=596, generation_context=f.context), f.registry)

    def paid(self, g, cid, target=None, player=1):
        cost = g.registry.card(cid).cost; mana = g.state.players[player].mana
        identity = self.play(g, cid, target, player); row = g.state.play_history[-1]
        self.assertEqual((row.card_id, row.cost), (cid, cost))
        if cid != COMMUNION:self.assertEqual(g.state.players[player].mana, mana-cost)
        return identity

    def test_complete_six_rows_twelve_faces_original_child_ids_and_hidden_zero(self):
        data = native.load_batch(); self.assertEqual(len(data['dependencies']), 6); self.assertEqual(len(data['official_observations']), 12)
        rows = {v['record']['id']:v['record'] for v in data['dependencies']}
        for row in data['official_observations']:batch.check_face(rows[row['card_id']], row['face'], row['locale'],
            numeric_normalizations=data['numeric_normalizations'].get(row['card_id']))
        self.assertEqual(rows[MASS]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'], rows[SHEEP]['dbf_id'])
        self.assertIsNone(rows[EXCESS]['cost']); self.assertEqual(host().registry.card(EXCESS).cost, 0)
        self.assertEqual(host().registry.card(CALL).hand_derivatives[0].card_id, TWIN); self.assertEqual(native.COLLECTIBLE_ROOTS, ())

    def test_communion_real_paid_both_actors_discards_only_original_hand_then_gains_ten_available(self):
        for player in (1, 2):
            g = self.game((COMMUNION, UNIT, SECOND), player=player, maximum=5, cap=10)
            originals = tuple(i for i in g.state.players[player].hand if g.state.entities[i].card_id != COMMUNION)
            rng = g._rng.getstate(); self.paid(g, COMMUNION, player=player)
            self.assertEqual((g.state.players[player].max_mana, g.state.players[player].mana), (10, 10))
            self.assertEqual([v.entity_id for v in g.state.discard_history], list(originals)); self.assertFalse(g.state.players[player].hand)
            self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.death_history)
            if player == 1:self.portable(g)

    def test_at_cap_excess_is_created_after_discards_and_its_real_zero_cost_body_draws(self):
        g = self.game((COMMUNION, UNIT), deck=(SECOND,), maximum=10, cap=10); original = self.entity(g, SECOND, zone='deck').id
        self.paid(g, COMMUNION); self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [EXCESS])
        self.assertEqual(g.state.players[1].mana, 5); self.play(g, EXCESS)
        self.assertEqual(g.state.players[1].hand, [original]); self.assertEqual(len(g.state.draw_history), 1); self.portable(g)

    def test_custom_cap_and_temporary_available_mana_do_not_assume_ten_maximum(self):
        g = self.game((COMMUNION,), maximum=5, cap=20); self.paid(g, COMMUNION)
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (15, 10))
        g = self.game((COMMUNION, TEMP), maximum=5, cap=10); self.play(g, TEMP); self.paid(g, COMMUNION)
        self.assertEqual(g.state.players[1].max_mana, 5); self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [EXCESS])

    def test_discard_wait_retains_new_acquisition_and_original_queue_through_failed_resume(self):
        g = self.game((COMMUNION, UNIT, SECOND), maximum=5, cap=10, watch=True); self.paid(g, COMMUNION)
        self.assertEqual(len(g.state.discard_history), 1); self.assertEqual(g.state.players[1].max_mana, 5)
        other = self.portable(g); saved = other.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):self.choose(other, 'fault')
        self.assertEqual(other.snapshot(), saved); self.choose(other)
        self.assertEqual([other.state.entities[i].card_id for i in other.state.players[1].hand], [ADDED])
        self.assertEqual(len(other.state.discard_history), 2); self.assertEqual(other.state.players[1].mana, 10); self.portable(other)

    def test_discard_original_that_moves_during_first_reaction_is_not_rebound(self):
        g = self.game((COMMUNION, UNIT, SECOND), maximum=5, cap=10, watch=True); second = self.entity(g, SECOND).id
        self.paid(g, COMMUNION); self.choose(g, 'move')
        self.assertIn(second, g.state.players[1].deck); self.assertEqual(len(g.state.discard_history), 1)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [ADDED]); self.portable(g)

    def test_mass_both_original_boards_transform_without_deathrattles_and_preserve_physical_order(self):
        for player in (1, 2):
            g = self.game((MASS,), own=(UNIT, SECOND), enemy=(UNIT,), player=player)
            boards = {p:tuple(g.state.players[p].board) for p in (1, 2)}; rng = g._rng.getstate(); self.paid(g, MASS, player=player)
            for p, ids in boards.items():
                self.assertEqual(tuple(g.state.players[p].board), ids)
                self.assertEqual([(g.state.entities[i].card_id, g.state.entities[i].attack, g.state.entities[i].health) for i in ids], [(SHEEP, 1, 1)]*len(ids))
            self.assertFalse(g.state.death_history); self.assertEqual(g._rng.getstate(), rng); self.assertEqual(len(g.state.card_summon_history), 0)
            if player == 1:self.portable(g)

    def test_mass_lost_health_aura_cannot_kill_later_original_before_its_sheep_face(self):
        g = self.game((PREP, MASS), own=(AURA, FRAGILE), enemy=(SECOND,), watch=True)
        self.play(g, PREP); self.assertEqual(self.entity(g, FRAGILE, zone='board').health, 1)
        self.paid(g, MASS); self.assertIsNotNone(g.state.pending_choice); self.assertFalse(g.state.death_history)
        self.assertTrue(all(g.state.entities[i].card_id == SHEEP for p in (1, 2) for i in g.state.players[p].board))
        other = self.portable(g); saved = other.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):self.choose(other, 'fault')
        self.assertEqual(other.snapshot(), saved); self.choose(other)
        self.assertEqual(other.state.entities[other.state.players[1].hero_id].armor, 3); self.assertFalse(other.state.death_history); self.portable(other)

    def test_mass_excludes_dormancy_and_locations_but_is_not_targeted_by_stealth_elusive(self):
        g = self.game((MASS,), own=(FRAGILE, DORMANT, LOCATION)); dormant = self.entity(g, DORMANT, zone='board').id
        location = self.entity(g, LOCATION, zone='board').id; self.paid(g, MASS)
        self.assertEqual(g.state.entities[dormant].card_id, DORMANT); self.assertFalse(g.state.entities[dormant].active)
        self.assertEqual(g.state.entities[location].card_id, LOCATION); self.assertEqual(sum(g.state.entities[i].card_id == SHEEP for i in g.state.players[1].board), 1)

    def test_mass_empty_board_still_pays_once_without_rng(self):
        g = self.game((MASS,)); rng = g._rng.getstate(); self.paid(g, MASS)
        self.assertEqual(g._rng.getstate(), rng); self.assertIsNone(g.state.pending_choice); self.portable(g)

    def test_mass_uses_actual_podling_replacement_without_losing_deferred_original_receipt(self):
        g = self.game((MASS,), own=(PODLING, UNIT)); original = self.entity(g, PODLING, zone='board').id
        neighbor = self.entity(g, UNIT, zone='board').id; self.paid(g, MASS)
        self.assertEqual(g.registry.card(g.state.entities[original].card_id).cost, 3)
        self.assertEqual(g.state.entities[neighbor].card_id, SHEEP); self.assertFalse(g.state.death_history); self.portable(g)

    def test_calling_replaces_target_on_its_original_side_with_two_cost_matched_entries(self):
        for enemy in (False, True):
            g = self.game((CALL,), own=() if enemy else (UNIT,), enemy=(UNIT,) if enemy else ())
            recipient = 2 if enemy else 1; original = self.entity(g, UNIT, recipient, 'board').id
            self.paid(g, CALL, original)
            self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD); self.assertEqual(len(g.state.card_summon_history), 2)
            for root in g.state.card_summon_history:
                self.assertEqual((root.request.player_id, root.request.cause.player_id), (recipient, 1))
                self.assertTrue(all(g.registry.card(g.state.entities[i].card_id).cost == 0 for i in g.state.players[recipient].board))
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [TWIN])
            if enemy:self.portable(g)

    def test_calling_uses_local_board_cost_and_resolves_original_death_before_summons(self):
        g = self.game((COST, CALL), own=(SECOND,)); victim = self.entity(g, SECOND, zone='board').id
        self.play(g, COST)
        self.paid(g, CALL, victim)
        self.assertEqual([(r.request.pool_basis.query.min_cost, r.request.pool_basis.query.max_cost)
            for r in g.state.card_summon_history], [(1, 1), (1, 1)])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 99)
        died = next(e.sequence for e in g.events if e.kind == 'minion_died' and e.target_id == victim)
        summoned = [e.sequence for e in g.events if e.kind == 'minion_summoned']
        self.assertTrue(summoned and min(summoned) > died); self.portable(g)

    def test_calling_second_acceptance_observes_later_quantity_without_rewriting_first(self):
        g = self.game((CALL,), own=(UNIT, QUANTITY), watch=True); victim = self.entity(g, UNIT, zone='board').id
        self.paid(g, CALL, victim); self.assertEqual(len(g.state.card_summon_history), 1)
        other = self.portable(g); saved = other.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):self.choose(other, 'fault')
        self.assertEqual(other.snapshot(), saved); self.choose(other, 'double')
        self.assertEqual([len(row.deliveries) for row in other.state.card_summon_history], [1, 2]); self.assertEqual(len(other.state.players[1].board), 4)
        self.portable(other)

    def test_full_board_replacement_rechecks_capacity_for_each_original_root(self):
        g = self.game((CALL,), own=(UNIT,)*7); victim = g.state.players[1].board[0]; self.paid(g, CALL, victim)
        self.assertEqual(len(g.state.players[1].board), 7); self.assertEqual(len(g.state.card_summon_history), 2); self.portable(g)

    def test_twinspell_native_copy_has_same_body_but_cannot_generate_another_twin(self):
        g = self.game((CALL,), own=(UNIT, UNIT)); first, second = g.state.players[1].board
        self.paid(g, CALL, first); self.paid(g, TWIN, second)
        self.assertFalse(g.state.players[1].hand); self.assertEqual(len(g.state.card_summon_history), 4); self.portable(g)

    def test_automatic_calling_has_its_native_twinspell_derivative(self):
        g = self.game((AUTO,), own=(UNIT,)); self.play(g, AUTO)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [TWIN])
        self.assertEqual([row.card_id for row in g.state.play_history], [AUTO]); self.portable(g)

    def test_required_calling_target_rejects_before_payment(self):
        g = self.game((CALL,)); saved = g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g, CALL)
        self.assertEqual(g.snapshot(), saved)

    def test_unknown_named_destination_rolls_back_paid_source_and_all_original_targets(self):
        g = self.game((BAD_BATCH,), own=(UNIT, SECOND)); saved = g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g, BAD_BATCH)
        self.assertEqual(g.snapshot(), saved)

    def test_named_batch_rejects_bad_shapes_and_late_registration_is_atomic(self):
        g = self.game((MASS,), own=(UNIT,)); ref = MinionReference.capture(self.entity(g, UNIT, zone='board'))
        for values in ((ref, ref), [ref], (None,)):
            with self.assertRaises(ValueError):TransformMinionsToCard(values, SHEEP)
        r = batch.registration_prefix(build_registry, 'hs_sim.cards.past_arcane_board_replacements.register_past_arcane_board_replacements',
            native.register_past_arcane_board_replacements)
        r.register_pool_card(replace(host().registry.pool_card(TWIN), cost=9)); before = r.fingerprint()
        with self.assertRaisesRegex(TargetValidationError, TWIN):native.register_past_arcane_board_replacements(r)
        self.assertEqual(r.fingerprint(), before)

    def test_original_pending_group_and_previous_schema_remain_private_and_strict(self):
        g = self.game((COMMUNION, UNIT, SECOND), maximum=5, cap=10, watch=True); self.paid(g, COMMUNION)
        saved = json.loads(json.dumps(g.snapshot())); bad = deepcopy(saved); bad['schema_version'] = 602
        with self.assertRaises(ValueError):Game.from_snapshot(bad, host('independent-reader').registry)
        self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION, 603); self.portable(g)
        view = json.dumps(g.for_player(2).observe())
        for word in ('resolution_frame', 'rng_state', 'CardReference', 'discard_history', 'record_sha256'):
            self.assertNotIn('"'+word+'"', view)
        ref = batch.read(native.ROOT/'data/cards/past-arcane-local-reference-v1.json')
        self.assertEqual(len(ref['candidate_ids']), 84); self.assertFalse(any(s.source_card_id == 'TIME_857' for s in host().registry.generation_scopes.values()))
