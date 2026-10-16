"""Actual Barbed Thorn branches share physical hand/equipment lifecycles."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_weapon_choice_cards import THORN, POISON, SPIKES, CHOICE_ONLY, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, EquippedWeaponReference,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError,
    TriggerSpec, Zone)
from hs_sim.engine.choose_branch_state import SetChooseBranch, validate_selection_for_card
from hs_sim.engine.choose_one import DISPATCH, normalize
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, EquipWeapon, InvokeBehavior,
    RequestChoice, TransferWeapon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChooseBranchSelection
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference

YETI = 'CORE_CS2_182'
SWORD = 'EDR_457t'


def registry():
    r = build_registry()
    r.register_card(CardDefinition('k88.both', 'Existing Choose Both fixture', CardType.MINION,
                                   health=10, choose_both=True))
    r.register_card(CardDefinition('k88.bonus', 'Spell bonus fixture', CardType.MINION,
                                   health=10, spell_damage=3))
    r.register_card(CardDefinition('k88.shield', 'Shield fixture', CardType.MINION,
                                   health=10, keywords=(Keyword.DIVINE_SHIELD,)))
    r.register_card(CardDefinition('k88.sleep', 'Sleeping fixture', CardType.MINION,
                                   health=10, dormant_turns=2))
    r.register_behavior('k88.fail', lambda c: (AddToHand(c.player_id, 'unknown.k88'),))

    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('bad', 'Fail', (InvokeBehavior('k88.fail', c.source_id, c.player_id),)),
        ), source_id=c.source_id),)

    def observed(c, event):
        if c.event.kind != event:
            return ()
        subject = c.event.target_id if event == 'weapon_equipped' else c.event.source_id
        return wait(c) if subject is not None and c.state.entities[subject].card_id == THORN else ()

    for name, event in (('commit_wait', 'card_committed'), ('grant_wait', 'ability_granted'),
                        ('damage_wait', 'damage_dealt')):
        r.register_behavior('k88.'+name, lambda c, e=event: observed(c, e))
        r.register_card(CardDefinition('k88.'+name, name, CardType.MINION, health=10,
                                       triggers=(TriggerSpec(event, 'k88.'+name),)))
    r.register_behavior('k88.replace', lambda c: (EquipWeapon(c.player_id, SWORD),)
        if c.state.entities[c.event.target_id].card_id == THORN else ())
    r.register_card(CardDefinition('k88.replace', 'Equipment reaction fixture', CardType.MINION,
        health=10, triggers=(TriggerSpec('weapon_equipped', 'k88.replace'),)))
    r.register_behavior('k88.old_death', wait)
    r.register_card(CardDefinition('k88.old', 'Old waiting weapon', CardType.WEAPON,
                                   attack=1, durability=1, deathrattle='k88.old_death'))

    def preset(c, origin):
        entity = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                      if c.state.entities[i].card_id == THORN)
        return (SetChooseBranch(CardReference.capture(entity), POISON, (origin,), source_id=c.source_id),)

    scripts = {
        'break': lambda c: (Destroy(c.state.players[c.player_id].weapon_id, c.source_id),),
        'break_enemy': lambda c: (Destroy(c.state.players[3-c.player_id].weapon_id, c.source_id),),
        'equip': lambda c: (EquipWeapon(c.player_id, THORN),),
        'preset': lambda c: preset(c, 'hand'),
        'bad_cast': lambda c: preset(c, 'cast_effect'),
        'bad_physical': lambda c: preset(c, 'physical'),
        'take': lambda c: (TransferWeapon(EquippedWeaponReference.capture(
            c.state.entities[c.state.players[3-c.player_id].weapon_id]), c.player_id, c.source_id),),
    }
    for name, body in scripts.items():
        r.register_behavior('k88.'+name, body)
        r.register_card(CardDefinition('k88.'+name, name, CardType.SPELL, on_play='k88.'+name))
    r.validate()
    return r


class NativeWeaponChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(THORN,), board=(), enemy=(), enemy_hand=(), weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, weapon_card_id=weapon,
                        deck=(YETI,)*8, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*8,
                        mana=40, max_mana=40, mana_cap=40),
        ), seed=88), self.r)

    def play(self, g, cid=THORN, branch=POISON, target=None):
        p = g.state.active_player
        eid = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, eid, target_id=target, branch_id=branch if cid == THORN else None))
        return eid

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def drain(self, g):
        while g.state.pending_choice is not None:
            self.choose(g)

    def hero(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.for_player(p).legal_actions())
            for hidden in ('resolution_frame', 'rng_state', 'behavior_id', 'original_state_hash'):
                self.assertNotIn(hidden, public)
        return other

    def test_full_real_weapon_and_two_nonphysical_official_options(self):
        data = load_batch()
        card = self.r.card(THORN)
        self.assertEqual((card.kind, card.cost, card.attack, card.durability), (CardType.WEAPON, 3, 1, 3))
        self.assertEqual(card.on_play, DISPATCH)
        self.assertIsNone(card.battlecry)
        self.assertEqual(len(data['official_observations']['observations']), 6)
        self.assertEqual(tuple(b.id for b in card.choose_one.branches), CHOICE_ONLY)
        for cid in CHOICE_ONLY:
            self.assertTrue(self.r.card(cid).choice_only)
            self.assertFalse(self.r.card(cid).hand_playable)
            self.assertNotIn(cid, self.r.pool_cards)

    def test_native_weapon_branch_dispatch_does_not_enable_other_root_types(self):
        card = self.r.card(THORN)
        for kind in (CardType.LOCATION, CardType.HERO):
            with self.assertRaisesRegex(ValueError, 'Unsupported Choose One root declaration'):
                normalize(replace(card, kind=kind, on_play=None))
        self.assertEqual(normalize(card), card)

    def test_legal_branches_equip_original_once_and_pay_without_spell_or_battlecry(self):
        g = self.game()
        actions = [a for a in g.legal_actions() if type(a) is PlayCard]
        self.assertEqual({a.branch_id for a in actions}, {POISON, SPIKES})
        original = self.play(g)
        self.assertEqual(g.state.players[1].weapon_id, original)
        self.assertEqual(g.state.players[1].mana, 37)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(g.state.play_history[0].branch_id, POISON)
        self.assertFalse(g.state.cast_history)
        self.assertFalse(g.state.battlecry_history)
        self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_invalid_branch_or_target_does_not_pay_or_replace_old_weapon(self):
        for branch, target in ((None, None), ('missing', None), (THORN+':combined', None), (POISON, 1)):
            g = self.game(weapon=SWORD)
            before = g.snapshot()
            with self.assertRaises(IllegalAction):
                self.play(g, branch=branch, target=target)
            self.assertEqual(g.snapshot(), before)

    def test_direct_equipment_and_scenario_do_not_execute_hand_branch(self):
        for g in (self.game(hand=('k88.equip',)), self.game(hand=(), weapon=THORN)):
            if g.state.players[1].hand:
                self.play(g, 'k88.equip')
            weapon = g.state.entities[g.state.players[1].weapon_id]
            self.assertNotIn(Keyword.POISONOUS, weapon.keywords)
            self.assertFalse(any(a.kind == 'deathrattle' for a in weapon.abilities))
            self.assertIsNone(g.state.pending_choice)

    def test_poison_branch_contributes_to_actual_hero_attack(self):
        g = self.game(enemy=(YETI,))
        original = self.play(g)
        target = g.state.players[2].board[0]
        self.assertIn(Keyword.POISONOUS, self.hero(g).keywords)
        g.apply(Attack(1, self.hero(g).id, target))
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[original].durability, 2)
        self.assertEqual(self.hero(g).health, 26)
        self.portable(g)

    def test_shielded_zero_damage_does_not_poison_target(self):
        g = self.game(enemy=('k88.shield',))
        self.play(g)
        target = g.state.players[2].board[0]
        g.apply(Attack(1, self.hero(g).id, target))
        self.assertEqual(g.state.entities[target].health, 10)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[target].keywords)

    def test_poison_expires_on_original_turn_and_does_not_return_next_turn(self):
        g = self.game(enemy=(YETI,))
        original = self.play(g)
        g.apply(EndTurn(1))
        self.assertNotIn(Keyword.POISONOUS, g.state.entities[original].keywords)
        self.assertNotIn(Keyword.POISONOUS, self.hero(g).keywords)
        g.apply(EndTurn(2))
        target = g.state.players[2].board[0]
        g.apply(Attack(1, self.hero(g).id, target))
        self.assertEqual(g.state.entities[target].health, 4)
        self.portable(g)

    def test_deathrattle_is_delayed_enemy_only_effect_damage_without_spell_bonus(self):
        g = self.game((THORN, 'k88.break'), board=('k88.bonus', YETI), enemy=(YETI, YETI))
        original = self.play(g, branch=SPIKES)
        self.assertEqual(self.hero(g, 2).health, 30)
        self.assertNotIn(Keyword.POISONOUS, self.hero(g).keywords)
        self.play(g, 'k88.break')
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
        self.assertEqual(self.hero(g, 2).health, 28)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board], [3, 3])
        self.assertEqual([g.state.entities[i].health for i in g.state.players[1].board], [10, 5])
        self.assertEqual(len(g.state.deathrattle_history), 1)
        self.portable(g)

    def test_deathrattle_persists_after_turn_and_fires_on_opponent_destroy(self):
        g = self.game(enemy=(YETI,), enemy_hand=('k88.break_enemy',))
        self.play(g, branch=SPIKES)
        g.apply(EndTurn(1))
        self.play(g, 'k88.break_enemy')
        self.assertEqual(self.hero(g, 2).health, 28)
        self.assertEqual(self.hero(g).health, 30)
        self.assertEqual(len(g.state.deathrattle_history), 1)

    def test_replacement_triggers_only_old_weapon_granted_deathrattle(self):
        g = self.game((THORN, THORN), enemy=(YETI,))
        old = self.play(g, branch=SPIKES)
        current = self.play(g, branch=POISON)
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].weapon_id, current)
        self.assertEqual(self.hero(g, 2).health, 28)
        self.assertIn(Keyword.POISONOUS, g.state.entities[current].keywords)
        self.assertFalse(any(a.kind == 'deathrattle' for a in g.state.entities[current].abilities))
        self.portable(g)

    def test_equipment_reaction_replacement_does_not_grant_to_new_weapon(self):
        for branch in (POISON, SPIKES):
            g = self.game(board=('k88.replace',))
            original = self.play(g, branch=branch)
            current = g.state.entities[g.state.players[1].weapon_id]
            self.assertEqual(current.card_id, SWORD)
            self.assertNotEqual(current.id, original)
            self.assertNotIn(Keyword.POISONOUS, current.keywords)
            self.assertFalse(any(a.kind == 'deathrattle' for a in current.abilities))
            self.assertEqual(self.hero(g, 2).health, 30)
            self.portable(g)

    def test_old_weapon_death_wait_keeps_new_selected_branch_and_single_payment(self):
        g = self.game(weapon='k88.old')
        original = self.play(g, branch=SPIKES)
        self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.players[1].weapon_id, original)
        self.assertEqual(g.state.players[1].mana, 37)
        self.assertTrue(any(a.kind == 'deathrattle' for a in g.state.entities[original].abilities))

    def test_commit_wait_retains_branch_and_rollback_after_failure(self):
        g = self.game(board=('k88.commit_wait',))
        original = self.play(g, branch=SPIKES)
        before = g.snapshot()
        other = self.portable(g)
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertTrue(any(a.kind == 'deathrattle' for a in g.state.entities[original].abilities))

    def test_existing_choose_both_grants_both_to_one_paid_original(self):
        g = self.game(board=('k88.both',))
        original = self.play(g, branch=THORN+':combined')
        weapon = g.state.entities[original]
        self.assertIn(Keyword.POISONOUS, weapon.keywords)
        self.assertEqual(sum(a.kind == 'deathrattle' for a in weapon.abilities), 1)
        self.assertEqual(g.state.players[1].mana, 37)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(g.state.play_history[0].branch_id, THORN+':combined')
        self.portable(g)

    def test_wait_between_two_grants_restores_tail_and_original_identity(self):
        g = self.game(board=('k88.both', 'k88.grant_wait'))
        original = self.play(g, branch=THORN+':combined')
        self.assertIn(Keyword.POISONOUS, g.state.entities[original].keywords)
        self.assertFalse(any(a.kind == 'deathrattle' for a in g.state.entities[original].abilities))
        other = self.portable(g)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.drain(g)
        self.assertEqual(sum(a.kind == 'deathrattle' for a in g.state.entities[original].abilities), 1)
        self.portable(g)

    def test_actual_weapon_death_damage_wait_restore_failure_and_replay(self):
        g = self.game((THORN, 'k88.break'), board=('k88.damage_wait',), enemy=(YETI,))
        self.play(g, branch=SPIKES)
        self.play(g, 'k88.break')
        before = g.snapshot()
        other = self.portable(g)
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.drain(g)
        self.portable(g)

    def test_transferred_deathrattle_uses_current_weapon_controller(self):
        g = self.game(enemy_hand=('k88.take', 'k88.break'))
        original = self.play(g, branch=SPIKES)
        g.apply(EndTurn(1))
        self.play(g, 'k88.take')
        self.assertEqual(g.state.entities[original].owner, 1)
        self.assertEqual(g.state.entities[original].controller, 2)
        self.play(g, 'k88.break')
        self.assertEqual(self.hero(g).health, 28)
        self.assertEqual(self.hero(g, 2).health, 30)
        self.portable(g)

    def test_hand_preselection_uses_same_native_branch_without_extra_choice(self):
        g = self.game(('k88.preset', THORN))
        self.play(g, 'k88.preset')
        self.portable(g)
        actions = [a for a in g.legal_actions() if type(a) is PlayCard and g.state.entities[a.entity_id].card_id == THORN]
        self.assertEqual([a.branch_id for a in actions], [POISON])
        self.play(g)
        self.assertIsNone(g.state.pending_choice)

    def test_weapon_preselection_rejects_nonphysical_cast_and_summon_origins(self):
        for script in ('k88.bad_cast', 'k88.bad_physical'):
            g = self.game((script, THORN))
            before = g.snapshot()
            with self.assertRaisesRegex(ResolutionError, 'Preselected origin cannot activate'):
                self.play(g, script)
            self.assertEqual(g.snapshot(), before)
        for origin in ('cast_draw', 'cast_history', 'power_manual', 'power_effect'):
            with self.assertRaisesRegex(ValueError, 'Preselected origin cannot activate'):
                validate_selection_for_card(self.r.card(THORN), ChooseBranchSelection(THORN, POISON, (origin,)))

    def test_rehashed_waiting_branch_tampering_is_rejected(self):
        g = self.game(board=('k88.commit_wait',))
        self.play(g, branch=SPIKES)
        saved = deepcopy(g.snapshot())
        saved['state']['play_history'][0]['branch_id'] = POISON
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry())
