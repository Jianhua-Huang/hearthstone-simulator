"""Flashback's real paid/automatic entry, original draws and pre-entry bonus."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest
from unittest.mock import patch

from hs_sim.cards.native_past_entry_grant_cards import (
    FLASHBACK, POOL_ID, QUERY, load_batch, register_native_past_entry_grant_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, Scenario, SelectChoice, Zone)
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.effects import (Buff, ChoiceOption, Destroy, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import SummonQuantitySpec, SummonStats, TargetSpec, TriggerSpec
from hs_sim.engine.pools import (GenerateFromPool, GenerationContext, PoolCard, PoolDefinition,
    PoolMember, SummonFromPool)
from hs_sim.engine.pool_summons import PoolSummonEntryLink, entry_material
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import (SummonByCard, SummonCause, SummonEntryMaterial,
    validate_material, validate_request)

P = 'k184.'
HERO, A, B, MAGNETIC, PIECE, UNKNOWN = (P + s for s in ('hero', 'a', 'b', 'magnetic', 'piece', 'unknown'))
CTX = GenerationContext('k184-explicit-bounded-past-fixture', 'experimental')
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def registry(members=(A, B), mode=None, bonus=1, pool='complete', role='writer'):
    # These finite inventories test the runtime contract, not official past membership.
    r = Registry('k184-native-entry-v1')
    register_native_past_entry_grant_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100,
        metadata=replace(META, collectible=False, classes=(CardClass.ROGUE,))))
    r.register_behavior(P + 'bc', lambda c: (GainArmor(c.player_id, 777),))
    for cid, attack, kw in ((A, 2, ()), (B, 1, ()),
            (MAGNETIC, 1, (Keyword.MAGNETIC, Keyword.RUSH)), (PIECE, 1, (Keyword.STARSHIP_PIECE,))):
        card = CardDefinition(cid, cid, CardType.MINION, cost=1, attack=attack, health=3,
            metadata=replace(META, classes=(CardClass.MAGE,)) if cid == B else
                replace(META, tribes=('mech',)) if cid == MAGNETIC else META,
            keywords=kw, magnetic_tribes=('mech',) if cid == MAGNETIC else (),
            battlecry=P + 'bc' if cid == B else None)
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 1, META,
            battlecry=False, deathrattle=False, choose_one=False))
    if pool != 'absent':
        r.register_pool(PoolDefinition(POOL_ID, 'k184-bounded-complete-v1', CTX.target_id, CTX.mode,
            tuple(PoolMember(cid, 2 if cid == A else 3) for cid in members), complete=pool == 'complete'))
    def fail(c): raise ResolutionError('K184 deliberate late failure')
    r.register_behavior(P + 'fail', fail)
    scripts = {
        'starter': lambda c: (),
        'auto': lambda c: (CastSpell(c.player_id, FLASHBACK, c.source_id, choices='player'),),
        'single': lambda c: (SummonFromPool(c.player_id, POOL_ID, QUERY, source_id=c.source_id,
            cause=SummonCause.capture(c)),),
        'silence': lambda c: (Silence(c.target_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
    }
    for key, body in scripts.items():
        r.register_behavior(P + key, body)
        r.register_card(CardDefinition(P + key, key, CardType.SPELL, on_play=P + key,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
                if key in ('silence', 'bounce', 'kill') else None))
    r.register_card(CardDefinition(P + 'twice', 'Existing spell summon quantity', CardType.MINION,
        health=9, summon_quantities=(SummonQuantitySpec(2),)))
    if mode:
        def observe(c):
            e = c.state.entities[c.event.target_id]
            if e.card_id not in members: return ()
            base = 2 if e.card_id == A else 1
            if (e.attack, e.max_health) != (base + bonus, 3):
                raise ResolutionError('First summon notification missed the relative Attack grant')
            work = (GainArmor(c.player_id, 1),)
            if mode == 'fail': return (*work, InvokeBehavior(P + 'fail', c.source_id, c.player_id))
            if mode == 'change' and len(c.state.card_summon_history) == 1 and len(c.state.card_summon_history[0].deliveries) == 1:
                work += tuple(Destroy(i, c.source_id) for i in c.state.players[1].board
                    if c.state.entities[i].card_id == P + 'twice')
                work += (Buff(e.id, attack=20, source_id=c.source_id),)
            if mode in ('wait', 'change'):
                work += (RequestChoice(c.player_id, (
                    ChoiceOption('ok', 'Continue'),
                    ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),))), c.source_id),)
            return work
        r.register_behavior(P + 'observe', observe)
        r.register_card(CardDefinition(P + 'watch', 'First summon observer', CardType.MINION, health=9,
            triggers=(TriggerSpec('minion_summoned', P + 'observe'),)))
    r.validate()
    return r


class NativePastEntryGrantTests(unittest.TestCase):
    def game(self, members=(A, B), mode=None, bonus=1, pool='complete', board=(), hand=None, seed=184):
        self.config = (members, mode, bonus, pool)
        if mode: board = (P + 'watch', *board)
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, board=board, hand=hand if hand is not None else (P+'starter', FLASHBACK),
                deck=(A,)*8, mana=20, max_mana=20, mana_cap=20),
            PlayerSetup(HERO, deck=(A,)*8)), seed=seed, generation_context=CTX), registry(*self.config))

    def play(self, g, cid, target=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid, target)); return eid

    def cast(self, g, combo=True):
        if combo: self.play(g, P+'starter')
        return self.play(g, FLASHBACK)

    def bodies(self, g):
        return [g.state.entities[d.entity.entity_id] for root in g.state.card_summon_history
            for d in root.deliveries if d.outcome == 'delivered']

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def finish_choices(self, g):
        while g.state.pending_choice: self.choose(g)

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config, role='reader'))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config, role='reader')).snapshot(), saved)
        for player in (1, 2):
            text = json.dumps(g.for_player(player).observe()) + json.dumps(g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('entry_grant', 'pool_basis', 'resolution_frame', 'rng_state', 'behavior_id'):
                self.assertNotIn('"'+key+'"', text)
        return other

    def reject(self, saved):
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry(*self.config, role='reader'))

    def test_full_source_faces_real_combo_keyword_and_central_registration(self):
        d = load_batch(); raw = d['cards'][0]['record']
        self.assertEqual((raw['id'], raw['cost'], raw['tags']['CLASS'], raw['tags']['COMBO']), (FLASHBACK, 2, 7, 1))
        self.assertEqual({x['locale'] for x in d['official_observations'][FLASHBACK]}, {'zh_CN', 'en_US'})
        self.assertFalse(d['formal_pool_complete']); self.assertFalse(d['cn_calibrated'])
        from hs_sim.cards import build_registry
        r = build_registry()
        self.assertEqual(r.card(FLASHBACK), registry().card(FLASHBACK))
        self.assertIn(Keyword.COMBO, r.card(FLASHBACK).keywords)
        self.assertFalse(any(key[0] == POOL_ID for key in r._pools))

    def test_no_prior_play_summons_two_plain_original_entries(self):
        g = self.game(members=(A,), mode='check', bonus=0)
        self.cast(g, combo=False)
        self.assertEqual([(e.attack, e.health) for e in self.bodies(g)], [(2,3), (2,3)])
        self.assertIsNone(g.state.pool_summon_history[0].spec.basis.entry_grant)
        self.assertEqual(g.state.players[1].mana, 18)

    def test_combo_grant_is_relative_before_first_notification_and_paid_once(self):
        g = self.game(members=(A,), mode='check')
        source = self.cast(g)
        self.assertEqual([(e.attack, e.health) for e in self.bodies(g)], [(3,3), (3,3)])
        self.assertTrue(all(any(x.source_id == source and x.attack == 1 for x in e.enchantments) for e in self.bodies(g)))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.assertEqual(g.state.players[1].mana, 18)
        self.assertEqual([x.card_id for x in g.state.play_history], [P+'starter', FLASHBACK])

    def test_complete_weighted_draws_keep_all_classes_and_use_exactly_two_rng_draws(self):
        g = self.game()
        rng = Random(); rng.setstate(g._rng.getstate())
        expected = tuple(A if rng.randrange(5) < 2 else B for _ in range(2))
        self.cast(g)
        self.assertEqual(g.state.pool_summon_history[0].selected, expected)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual([e.card_id for e in self.bodies(g)], list(expected))
        self.assertTrue(all(e.attack == (3 if e.card_id == A else 2) for e in self.bodies(g)))

    def test_summoned_battlecry_minion_keeps_its_body_without_playing_battlecry(self):
        g = self.game(members=(B,))
        self.cast(g)
        self.assertEqual([(e.attack, e.health) for e in self.bodies(g)], [(2,3), (2,3)])
        self.assertFalse(g.state.battlecry_history)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)

    def test_two_original_entries_each_duplicate_same_granted_material_without_extra_rng(self):
        g = self.game(members=(A,), board=(P+'twice',))
        rng = Random(); rng.setstate(g._rng.getstate()); rng.randrange(2); rng.randrange(2)
        self.cast(g)
        self.assertEqual([r.plan.total for r in g.state.card_summon_history], [2,2])
        self.assertEqual([e.attack for e in self.bodies(g)], [3]*4)
        self.assertEqual(len({e.enchantments[-1].id for e in self.bodies(g)}), 4)
        self.assertEqual(g._rng.getstate(), rng.getstate())

    def test_later_original_entry_recaptures_quantity_but_first_keeps_original_plan_and_grant(self):
        g = self.game(members=(A,), mode='change', board=(P+'twice',))
        self.cast(g); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.bodies(g)[0].attack, 23)
        other = self.portable(g)
        self.finish_choices(g); self.finish_choices(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual([r.plan.total for r in g.state.card_summon_history], [2,1])
        self.assertEqual([e.attack for e in self.bodies(g)], [23,3,3])

    def test_full_board_keeps_batch_draws_and_original_failed_entry_attempts(self):
        g = self.game(members=(A,), board=(A,)*7)
        rng = Random(); rng.setstate(g._rng.getstate()); rng.randrange(2); rng.randrange(2)
        self.cast(g)
        self.assertFalse(self.bodies(g)); self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual(len(g.state.card_summon_history), 2)
        self.assertTrue(all(r.deliveries[0].outcome == 'board_full' for r in g.state.card_summon_history))

    def test_one_free_slot_does_not_reselect_or_lose_original_two_entry_plans(self):
        g = self.game(members=(A,), board=(P+'twice', A, A, A, A, A))
        self.cast(g)
        self.assertEqual([r.plan.total for r in g.state.card_summon_history], [2,2])
        self.assertEqual([e.attack for e in self.bodies(g)], [3])
        self.assertEqual([d.outcome for r in g.state.card_summon_history for d in r.deliveries],
            ['delivered', 'board_full', 'board_full', 'board_full'])

    def test_empty_complete_pool_costs_two_mana_without_rng_or_fake_summons(self):
        g = self.game(members=()); rng = g._rng.getstate()
        self.cast(g)
        self.assertEqual(g.state.pool_summon_history[0].selected, ())
        self.assertFalse(g.state.card_summon_history)
        self.assertEqual(g._rng.getstate(), rng); self.assertEqual(g.state.players[1].mana, 18)

    def test_unknown_eligible_candidate_errors_before_rng_even_when_board_is_full(self):
        for board in ((), (A,)*7):
            g = self.game(members=(A, UNKNOWN), board=board); self.play(g, P+'starter'); saved = g.snapshot()
            with patch.object(Random, 'randrange', side_effect=AssertionError('Unknown candidate was cropped')):
                with self.assertRaises(ResolutionError): self.play(g, FLASHBACK)
            self.assertEqual(g.snapshot(), saved)

    def test_absent_host_pool_fails_with_payment_and_rng_rollback(self):
        g = self.game(pool='absent'); self.play(g, P+'starter'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, FLASHBACK)
        self.assertEqual(g.snapshot(), saved)

    def test_magnetic_past_candidate_enters_as_independent_body_with_and_without_combo(self):
        for combo in (False, True):
            g = self.game(members=(MAGNETIC,), board=(MAGNETIC,))
            self.cast(g, combo=combo)
            self.assertEqual(len(g.state.players[1].board), 3)
            self.assertEqual([e.attack for e in self.bodies(g)], [2 if combo else 1]*2)
            self.assertTrue(all(Keyword.RUSH in e.keywords and Keyword.MAGNETIC in e.keywords for e in self.bodies(g)))
            self.assertFalse(g.state.magnetic_history)

    def test_single_attributed_pool_entry_accepts_plain_magnetic_and_starship_piece(self):
        for cid in (MAGNETIC, PIECE):
            g = self.game(members=(cid,), hand=(P+'single',))
            self.play(g, P+'single')
            self.assertEqual([e.card_id for e in self.bodies(g)], [cid])
            self.assertEqual(self.bodies(g)[0].attack, 1)

    def test_silence_and_bounce_use_existing_numeric_attachment_lifecycle(self):
        g = self.game(members=(A,), hand=(P+'starter', FLASHBACK, P+'silence', P+'bounce'))
        self.cast(g); first, second = self.bodies(g)
        self.play(g, P+'silence', first.id); self.assertEqual(g.state.entities[first.id].attack, 2)
        self.play(g, P+'bounce', second.id)
        self.assertEqual((g.state.entities[second.id].zone, g.state.entities[second.id].attack), (Zone.HAND, 2))

    def test_waiting_restore_clone_replay_and_failed_resume_keep_original_grants_and_rng(self):
        g = self.game(members=(A,), mode='wait', board=(P+'twice',))
        self.cast(g); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.finish_choices(g); self.finish_choices(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual([e.attack for e in self.bodies(g)], [3]*4)
        self.portable(g)

    def test_late_summon_reaction_failure_rolls_back_payment_draws_grants_and_all_history(self):
        g = self.game(members=(A,), mode='fail'); self.play(g, P+'starter'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, FLASHBACK)
        self.assertEqual(g.snapshot(), saved)

    def test_previous_turn_play_does_not_enable_current_combo(self):
        g = self.game(members=(A,)); self.play(g, P+'starter')
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, FLASHBACK)
        self.assertEqual([e.attack for e in self.bodies(g)], [2,2])

    def test_automatic_cast_uses_original_combo_source_and_no_extra_hand_payment(self):
        g = self.game(members=(A,), hand=(P+'auto',))
        source = self.play(g, P+'auto')
        self.assertEqual([e.attack for e in self.bodies(g)], [3,3])
        self.assertEqual(g.state.players[1].mana, 20)
        self.assertEqual([x.card_id for x in g.state.play_history], [P+'auto'])
        cast = next(x for x in g.state.cast_history if x.card_id == FLASHBACK)
        self.assertEqual(g.state.pool_summon_history[0].spec.cause.source.entity_id, cast.source_id)
        self.assertEqual(g.state.entities[cast.source_id].origin_entity_id, source)
        self.portable(g)

    def test_resealed_grant_parent_child_and_scope_tampering_are_rejected(self):
        g = self.game(members=(A,), mode='wait'); self.cast(g)
        for change in ('parent', 'child', 'source', 'scope'):
            saved = deepcopy(g.snapshot())
            if change == 'parent': saved['state']['pool_summon_history'][0]['spec']['basis']['entry_grant']['attack'] = 2
            elif change == 'child': saved['state']['card_summon_history'][0]['request']['materials'][0]['entry_grant'] = None
            elif change == 'source': saved['state']['pool_summon_history'][0]['spec']['basis']['source'] = None
            else: saved['state']['pool_summon_history'][0]['spec']['basis']['entry_grant']['health'] = 1
            self.reject(saved)
        saved = deepcopy(g.snapshot()); saved['schema_version'] = SNAPSHOT_SCHEMA_VERSION - 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry(*self.config))

    def test_unbound_or_inconsistent_pool_material_cannot_borrow_grant_or_magnetic_scope(self):
        g = self.game(members=(A,)); self.cast(g)
        request = g.state.card_summon_history[0].request
        with self.assertRaises(ValueError): validate_request(g.state, g.registry,
            replace(request, producer_link=PoolSummonEntryLink(999, 0)))
        with self.assertRaises(ValueError): validate_request(g.state, g.registry,
            replace(request, materials=(SummonEntryMaterial(A, entry_grant=CreatedMinionGrant(2)),)))
        with self.assertRaises(ValueError): validate_material(g.registry, SummonEntryMaterial(MAGNETIC))
        basis = g.state.pool_summon_history[0].spec.basis
        weighted = SummonByCard(1, tuple(entry_material(basis, m.card_id) for m in basis.candidates),
            request.cause, 'weighted', weights=tuple(m.weight for m in basis.candidates), pool_basis=basis)
        validate_request(g.state, g.registry, weighted)
        with self.assertRaises(ValueError): validate_request(g.state, g.registry,
            replace(weighted, materials=(SummonEntryMaterial(A, entry_grant=CreatedMinionGrant(2)),)))

    def test_new_entry_grant_rejects_unrelated_or_unattributed_creation_recipes(self):
        g = self.game(members=(A,)); self.cast(g)
        cause = g.state.pool_summon_history[0].spec.cause
        request = GenerateFromPool(1, POOL_ID, QUERY, source_id=cause.source.entity_id,
            destination='board', cause=cause, entry_grant=CreatedMinionGrant(1))
        for changes in ({'destination':'hand'}, {'source_id':None}, {'cause':None},
                {'player_id':2}, {'entry_grant':CreatedMinionGrant(health=1)}):
            with self.assertRaises(ValueError): replace(request, **changes)
        with self.assertRaises(ValueError): SummonEntryMaterial(A, stats=SummonStats(1,1), entry_grant=CreatedMinionGrant(1))


if __name__ == '__main__': unittest.main()
