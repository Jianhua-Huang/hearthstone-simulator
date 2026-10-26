"""Native fixtures stay separate from the full thirteen-member capability gate."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import candidate_pool_rows
from hs_sim.cards.past_colossal_controls import (SINDRAGOSA, CRABATOA, BODY,
    load_batch, register_past_colossal_controls)
from hs_sim.engine import (Attack, AuraSpec, CardClass, CardDefinition, CardMetadata,
    CardType, Game, Keyword, PlayerSetup, ResolutionError, Scenario, SnapshotError,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    EquipWeapon, Freeze, GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand,
    Silence, Summon, Unfreeze)
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, sample_candidates
from hs_sim.engine.serialization import canonical_hash
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k580.'
UNIT, WATCH, KILL, QUIET, CONTROL, BOUNCE, COPY, ADD_CRAB, FREEZE, THAW, SHIELD, NO_FREEZE, EQUIP, WRONG = (
    P+x for x in ('unit', 'watch', 'kill', 'silence', 'control', 'bounce', 'copy', 'crab',
        'freeze', 'thaw', 'shield', 'no-freeze', 'equip', 'wrong'))
SOURCE, FROST = 'CATA_EVENT_000', 'CORE_CS2_024'
CLAWS, WINGS, WEAPON = ('TSC_937t', 'TSC_937t3'), ('NX2_037t', 'NX2_037t2'), 'TSC_937t2'
CONTEXT = GenerationContext(P+'full-reference', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None)


@lru_cache(None)
def reference():
    from hs_sim.cards.past_colossal_controls import REFERENCE_PATH
    return batch.read(REFERENCE_PATH)


@lru_cache(None)
def host(mode='crab', role='writer'):
    r = build_cn37_local_pool_format().registry
    rows = candidate_pool_rows(batch=dict(cards=reference()['candidate_records'], printed_keyword_overrides={}),
        zero_costs={}, zero_attacks={})
    for row in rows:
        if row.card_id not in r.pool_cards: r.register_pool_card(row)
    # Two explicit single-card native fixtures test adapters. The full source
    # retains all thirteen and must reject before RNG while five bodies lack.
    ids = reference()['candidate_ids'] if mode == 'full-reference' else (
        SINDRAGOSA if mode in ('sind', 'wait-freeze') else CRABATOA,)
    r.register_pool(PoolDefinition('constructed.past.cards', P+'explicit-fixture:'+mode,
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in ids), complete=True))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=20, metadata=META))
    def fail(c): raise ResolutionError('K580 deliberate late reaction failure')
    def watch(c):
        if ((mode == 'wait-freeze' and c.event.kind == 'frozen') or
                (mode == 'wait-weapon' and c.event.kind == 'weapon_equipped')):
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'continue', ()),
                ChoiceOption('bad', 'fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        return ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=tuple(TriggerSpec(e, P+'watch') for e in ('frozen', 'weapon_equipped'))))
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        CONTROL: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        ADD_CRAB: lambda c: (Summon(c.player_id, CRABATOA),),
        FREEZE: lambda c: (Freeze(c.target_id, c.source_id),),
        THAW: lambda c: (Unfreeze(c.target_id),),
        SHIELD: lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        NO_FREEZE: lambda c: (GrantKeyword(c.target_id, Keyword.CANT_BE_FROZEN, c.source_id),),
        EQUIP: lambda c: (EquipWeapon(c.player_id, WEAPON),),
        WRONG: lambda c: (EquipWeapon(c.player_id, 'CS2_106'),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        targeting = None if cid in (ADD_CRAB, EQUIP, WRONG) else TargetSpec(TargetMode.REQUIRED,
            zones=(Zone.BOARD, Zone.HERO), kinds=(CardType.MINION, CardType.HERO))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=targeting, metadata=META))
    r.validate(); return r


def fixture(mode='crab', role='writer'): return host(mode, role)


@lru_cache(None)
def seed_for(cid):
    rows = tuple(PoolMember(x) for x in sorted(reference()['candidate_ids']))
    return next(seed for seed in range(1000) if sample_candidates(Random(seed), rows, 1, replacement=True) == (cid,))


class PastColossalControlsTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)
    mode = 'crab'

    def game(self, cid=CRABATOA, *, hand=(), enemy=(UNIT,), own=(), player=1, mode=None, opposing_weapon=None):
        mode = ('sind' if cid == SINDRAGOSA else 'crab') if mode is None else mode
        self.mode = mode
        if mode.startswith('wait-'): own = (WATCH, *own)
        players = tuple(PlayerSetup('HERO_03' if p == player else 'HERO_08',
            hand=(SOURCE, *hand) if p == player else (), board=own if p == player else enemy,
            deck=(UNIT,)*8, mana=40, max_mana=40, mana_cap=40,
            weapon_card_id=opposing_weapon if p != player else None) for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=player, seed=seed_for(cid),
            generation_context=CONTEXT), host(mode))

    def reward(self, g, cid=CRABATOA, player=1):
        self.play(g, SOURCE, player=player)
        self.entity(g, cid, player)
        return self.play(g, cid, player=player)

    def weapon(self, g, player=1): return g.state.entities[g.state.players[player].weapon_id]

    def test_full_reference_and_bilingual_root_faces_preserve_all_thirteen_without_native_coverage_filter(self):
        data = load_batch(); ref = reference(); r = host('full-reference')
        self.assertEqual(len(ref['candidate_ids']), 13)
        self.assertEqual(len(ref['candidate_records'])+len(ref['other_set_colossal_records']), 24)
        self.assertFalse(ref['membership_uses_executable_coverage']); self.assertFalse(ref['runtime_bindings_added'])
        self.assertFalse(ref['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        for row in data['cards']:
            for face in [x for x in data['official_observations'] if x['card_id'] == row['record']['id']]:
                batch.check_face(row['record'], face['face'], face['locale'])
        self.assertEqual(tuple(m.card_id for m in r.pool('constructed.past.cards', CONTEXT).members), tuple(ref['candidate_ids']))
        self.assertEqual(len([cid for cid in ref['candidate_ids'] if cid not in r.cards]), 5)
        self.assertTrue(all(Keyword.COLOSSAL in r.pool_card(cid).keywords for cid in ref['candidate_ids']))

    def test_both_native_rewards_real_paid_source_explicit_single_card_fixtures_and_ordered_entry_in_both_seats(self):
        for player, cid in ((1, SINDRAGOSA), (2, CRABATOA)):
            g = self.game(cid, player=player); eid = self.reward(g, cid, player)
            self.assertEqual(tuple(m.card_id for m in g.registry.pool('constructed.past.cards', CONTEXT).members), (cid,))
            limbs = WINGS if cid == SINDRAGOSA else CLAWS
            board = [g.state.entities[i].card_id for i in g.state.players[player].board]
            self.assertEqual(board, [SOURCE, limbs[0], cid, limbs[1]])
            self.assertEqual(g.state.players[player].mana, 40-g.registry.card(SOURCE).cost-g.registry.card(cid).cost)
            self.assertEqual(g.state.entities[eid].zone, Zone.BOARD)

    def test_sindragosa_wing_positive_combat_damage_freezes_and_destroys_actual_enemy(self):
        g = self.game(SINDRAGOSA); self.reward(g, SINDRAGOSA)
        wing = self.entity(g, WINGS[0], zone='board').id; target = g.state.players[2].board[0]
        g.apply(Attack(1, wing, target))
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(next(d for d in g.state.death_history if d.entity_id == target).cause.kind, 'destroy')
        self.assertTrue(any(e.kind == 'frozen' and e.target_id == target for e in g._events))

    def test_sindragosa_actual_frostbolt_kills_enemy_but_friendly_minion_and_enemy_hero_survive_freeze(self):
        g = self.game(SINDRAGOSA, hand=(FROST, FREEZE, FREEZE), own=(UNIT,))
        self.reward(g, SINDRAGOSA); target = g.state.players[2].board[0]
        self.play(g, FROST, target); self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        own = self.entity(g, UNIT, zone='board').id; self.play(g, FREEZE, own)
        hero = g.state.players[2].hero_id; self.play(g, FREEZE, hero)
        self.assertEqual(g.state.entities[own].zone, Zone.BOARD); self.assertTrue(g.state.entities[hero].frozen)

    def test_shield_and_cannot_be_frozen_do_not_create_a_false_enemy_destruction(self):
        for protection in (SHIELD, NO_FREEZE):
            g = self.game(SINDRAGOSA, hand=(protection,)); self.reward(g, SINDRAGOSA)
            target = g.state.players[2].board[0]; self.play(g, protection, target)
            g.apply(Attack(1, self.entity(g, WINGS[0], zone='board').id, target))
            self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
            self.assertFalse(g.state.entities[target].frozen)

    def test_existing_freeze_does_not_retrigger_until_actual_unfreeze_and_refreeze(self):
        g = self.game(SINDRAGOSA, hand=(FREEZE, FREEZE, THAW, FREEZE))
        target = g.state.players[2].board[0]; self.play(g, FREEZE, target)
        self.reward(g, SINDRAGOSA); self.play(g, FREEZE, target)
        self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.play(g, THAW, target); self.play(g, FREEZE, target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_silenced_sindragosa_keeps_enemy_frozen_without_destroying_it(self):
        g = self.game(SINDRAGOSA, hand=(QUIET, FREEZE)); eid = self.reward(g, SINDRAGOSA)
        self.play(g, QUIET, eid); target = g.state.players[2].board[0]; self.play(g, FREEZE, target)
        self.assertTrue(g.state.entities[target].frozen); self.assertEqual(g.state.entities[target].zone, Zone.BOARD)

    def test_crabatoa_healthy_native_aura_buffs_both_claws_and_real_deathrattle_weapon_and_hero_attack(self):
        g = self.game(); self.reward(g)
        self.assertEqual([self.entity(g, cid, zone='board').attack for cid in CLAWS], [4, 4])
        target = g.state.players[2].board[0]
        g.apply(Attack(1, self.entity(g, CLAWS[0], zone='board').id, target))
        self.assertEqual(self.weapon(g).card_id, WEAPON); self.assertEqual(self.weapon(g).attack, 4)
        hero = g.state.players[1].hero_id; self.assertEqual(g.state.entities[hero].attack, 4)
        old_health = g.state.entities[g.state.players[2].hero_id].health
        g.apply(Attack(1, hero, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, old_health-4)
        self.assertIsNone(g.state.players[1].weapon_id)
        g.apply(Attack(1, self.entity(g, CLAWS[1], zone='board').id, target))
        self.assertEqual(self.weapon(g).attack, 4); self.assertEqual(g.state.entities[hero].attacks_this_turn, 1)

    def test_named_weapon_selector_does_not_buff_other_weapons_and_source_silence_removes_both_populations(self):
        g = self.game(hand=(EQUIP, WRONG, EQUIP, QUIET)); eid = self.reward(g)
        self.play(g, WRONG); self.assertEqual(self.weapon(g).attack, g.registry.card('CS2_106').attack)
        self.play(g, EQUIP); self.assertEqual(self.weapon(g).attack, 4)
        self.play(g, QUIET, eid); self.assertEqual(self.weapon(g).attack, 2)
        self.assertEqual([self.entity(g, cid, zone='board').attack for cid in CLAWS], [2, 2])

    def test_two_real_sources_stack_then_bounce_removes_only_its_own_contribution(self):
        g = self.game(hand=(ADD_CRAB, EQUIP, BOUNCE)); eid = self.reward(g)
        self.play(g, ADD_CRAB); self.play(g, EQUIP)
        self.assertEqual(self.weapon(g).attack, 6)
        self.assertEqual(self.entity(g, CLAWS[0], zone='board').attack, 6)
        self.play(g, BOUNCE, eid); self.assertEqual(self.weapon(g).attack, 4)
        self.assertEqual(self.entity(g, CLAWS[0], zone='board').attack, 4)

    def test_control_transfer_moves_aura_to_new_current_weapon_and_current_copy_retains_named_selector(self):
        g = self.game(hand=(EQUIP, CONTROL), opposing_weapon=WEAPON); eid = self.reward(g); self.play(g, EQUIP)
        self.play(g, CONTROL, eid)
        self.assertEqual(self.weapon(g).attack, 2)
        self.assertEqual(self.weapon(g, 2).attack, 4)
        self.assertEqual([self.entity(g, cid, zone='board').attack for cid in CLAWS], [2, 2])
        h = self.game(hand=(EQUIP, COPY)); self.reward(h); self.play(h, EQUIP)
        self.play(h, COPY, self.entity(h, CRABATOA, zone='board').id)
        self.assertEqual(self.weapon(h).attack, 6)

    def test_original_freeze_waiting_restores_replays_and_failed_branch_rolls_back_before_native_destroy(self):
        g = self.game(SINDRAGOSA, hand=(FREEZE,), mode='wait-freeze'); self.reward(g, SINDRAGOSA)
        target = g.state.players[2].board[0]; self.play(g, FREEZE, target); before = g.snapshot()
        self.assertTrue(g.state.entities[target].frozen)
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); restored = self.portable(g)
        self.choose(g, 'ok'); self.choose(restored, 'ok')
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_equipped_weapon_waiting_saves_settled_named_bonus_and_resumes_after_restore(self):
        g = self.game(hand=(EQUIP,), mode='wait-weapon'); self.reward(g); self.play(g, EQUIP)
        self.assertEqual(self.weapon(g).attack, 4); restored = self.portable(g)
        self.choose(g, 'ok'); self.choose(restored, 'ok'); self.assertEqual(g.snapshot(), restored.snapshot())

    def test_full_thirteen_source_rejects_before_rng_even_for_known_selected_seed_and_rolls_back(self):
        g = self.game(SINDRAGOSA, mode='full-reference'); before = g.snapshot(); rng = g._rng.getstate()
        with self.assertRaises(ResolutionError): self.play(g, SOURCE)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(len(g.registry.pool('constructed.past.cards', CONTEXT).members), 13)
        self.assertIn('TSC_029', [m.card_id for m in g.registry.pool('constructed.past.cards', CONTEXT).members])

    def test_last_old_appendage_tampering_prevents_both_new_bodies_without_partial_registration(self):
        r = build_registry()
        for cid in (SINDRAGOSA, CRABATOA): del r._cards[cid]; del r._pool_cards[cid]
        del r._behaviors[BODY]
        r._cards[CLAWS[1]] = replace(r.card(CLAWS[1]), attack=3)
        before = (dict(r.cards), dict(r.pool_cards), dict(r._behaviors))
        with self.assertRaises(TargetValidationError): register_past_colossal_controls(r)
        self.assertEqual((dict(r.cards), dict(r.pool_cards), dict(r._behaviors)), before)

    def test_named_weapon_profile_rejects_blank_wrong_kind_and_changed_native_saved_selector(self):
        for changes in ({'card_ids': ()}, {'health': 1}, {'include_self': True}, {'adjacent_only': True}, {'attack': -1}):
            with self.assertRaises(ValueError): AuraSpec(**dict(dict(attack=2, target='friendly_weapon', card_ids=(WEAPON,)), **changes))
        r = build_registry()
        r._cards[CRABATOA] = replace(r.card(CRABATOA), auras=(AuraSpec(attack=2, target='friendly_weapon', card_ids=(CLAWS[0],)),))
        with self.assertRaises(ValueError): r.validate()
        g = self.game(hand=(EQUIP,)); eid = self.reward(g); self.play(g, EQUIP); saved = g.snapshot()
        ability = next(a for a in saved['state']['entities'][str(eid)]['abilities'] if a['kind'] == 'aura' and a['aura_target'] == 'friendly_weapon')
        ability['aura_card_ids'] = ['CS2_106']; saved['state_hash'] = canonical_hash(saved['state'])
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture('crab', 'independent-reader'))


if __name__ == '__main__': unittest.main()
