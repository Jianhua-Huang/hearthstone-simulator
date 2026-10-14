"""Meaningful isolated candidate tests, not canonical or formal acceptance."""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import unittest

import hs_sim
from hs_sim.engine import (ActivatedAbilitySpec, Attack, AttackPolicyCondition, AttackPolicySpec,
    AuraSpec, CardDefinition, CardType, EndTurn, Game, GrantAttackPolicy, IllegalAction,
    Keyword, KeywordAuraSpec, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, UseMinionAbility, Zone, TimedKeywordSpec,
    GrantStoredKeyword, CardReference, PlayerEffectSpec, AddPlayerEffect)
from hs_sim.engine.attack_policies import attack_limit
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, Effect, EquipWeapon, ForceAttack, Freeze, GainArmor, GrantKeyword,
    Heal, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


@dataclass(frozen=True)
class Unhandled(Effect):
    pass


class AttackPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(Path(hs_sim.__file__).resolve(), Path(__file__).resolve().parents[1] / 'hs_sim/__init__.py')
        self.r = Registry('isolated-attack-policies-candidate')
        self.r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=100))
        self.r.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=1, health=30))
        self.r.register_card(CardDefinition('mega', 'mega', CardType.MINION, attack=1, health=30,
                                            keywords=(Keyword.MEGA_WINDFURY,)))
        self.r.register_card(CardDefinition('wind', 'wind', CardType.MINION, attack=1, health=30,
                                            keywords=(Keyword.WINDFURY,)))
        self.r.register_card(CardDefinition('blocked', 'blocked', CardType.MINION, attack=1, health=30,
                                            attack_policies=(AttackPolicySpec('cannot_attack'),)))
        self.r.register_card(CardDefinition('nohero', 'nohero', CardType.MINION, attack=1, health=30,
                                            keywords=(Keyword.CHARGE,),
                                            attack_policies=(AttackPolicySpec('cannot_attack_heroes'),)))
        self.r.register_card(CardDefinition('infinite', 'infinite', CardType.MINION, attack=1, health=30,
                                            attack_policies=(AttackPolicySpec('attacks_per_turn'),)))
        self.r.register_card(CardDefinition('three', 'three', CardType.MINION, attack=1, health=30,
                                            attack_policies=(AttackPolicySpec('attacks_per_turn', 3),)))
        self.r.register_card(CardDefinition('fool', 'fool', CardType.WEAPON, attack=1, durability=8,
                                            attack_policies=(AttackPolicySpec('attacks_per_turn'),
                                                             AttackPolicySpec('cannot_attack_heroes'))))
        self.r.register_card(CardDefinition('weapon', 'weapon', CardType.WEAPON, attack=1, durability=8))
        self.r.register_card(CardDefinition('megaweapon', 'megaweapon', CardType.WEAPON, attack=1, durability=8,
                                            keywords=(Keyword.MEGA_WINDFURY,)))
        self.r.register_card(CardDefinition('mage', 'mage', CardType.MINION, attack=1, health=4, spell_damage=1))
        self.r.register_card(CardDefinition('aura', 'aura', CardType.MINION, attack=1, health=4,
                                            keyword_auras=(KeywordAuraSpec(Keyword.MEGA_WINDFURY, 'friendly_minions'),)))
        self.spell('freeze', lambda c: [Freeze(c.target_id)], True)
        self.spell('silence', lambda c: [Silence(c.target_id)], True)
        self.spell('kill', lambda c: [Destroy(c.target_id)], True)
        self.spell('hurt', lambda c: [Damage(c.target_id, 1)], True)
        self.spell('heal', lambda c: [Heal(c.target_id, 1)], True)
        self.spell('armor', lambda c: [GainArmor(c.player_id, 3)])
        self.spell('mega_grant', lambda c: [GrantKeyword(c.target_id, Keyword.MEGA_WINDFURY)], True)
        self.spell('block_grant', lambda c: [GrantAttackPolicy(c.target_id, AttackPolicySpec('cannot_attack'))], True)
        self.spell('temp_block', lambda c: [GrantAttackPolicy(c.target_id, AttackPolicySpec('cannot_attack'), expires_turn=c.state.turn)], True)
        self.spell('copy', lambda c: [CopyMinion(c.target_id, c.player_id)], True)
        self.spell('base_copy', lambda c: [CopyMinion(c.target_id, c.player_id, mode='base')], True)
        self.spell('bounce', lambda c: [ReturnToHand(c.target_id)], True)
        self.spell('transform', lambda c: [Transform(c.target_id, 'plain')], True)
        self.spell('steal', lambda c: [ChangeControl(c.target_id, c.player_id)], True)
        self.spell('equip', lambda c: [EquipWeapon(c.player_id, 'weapon')])
        self.spell('buff', lambda c: [Buff(c.target_id, attack=1)], True)

    def spell(self, name, behavior, targeted=False):
        self.r.register_behavior(name, behavior)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, requires_target=targeted))

    def conditional(self, name, attribute, comparison, value, **fields):
        self.r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=30,
            attack_policies=(AttackPolicySpec('cannot_attack', conditions=(
                AttackPolicyCondition(attribute, comparison, value),)),), **fields))

    def game(self, board=(), hand=(), enemy=('plain',), weapon=None, enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', board=board, hand=hand, deck=('plain',) * 10,
                        mana=10, max_mana=10, weapon_card_id=weapon),
            PlayerSetup('hero', board=enemy, hand=enemy_hand, deck=('plain',) * 10,
                        mana=10, max_mana=10)), seed=11), self.r)

    def unit(self, g, pos=0, player=1):
        return g.state.entities[g.state.players[player].board[pos]]

    def hero(self, g, player=2):
        return g.state.players[player].hero_id

    def cast(self, g, name, target=None):
        player = g.state.active_player
        entity_id = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(player, entity_id, target))

    def attack(self, g, target=None, source=None):
        return g.apply(Attack(g.state.active_player, source or self.unit(g).id,
                              target or self.hero(g)))

    def attacks(self, g, source=None):
        return [a for a in g.legal_actions() if isinstance(a, Attack) and
                (source is None or a.attacker_id == source)]

    def check(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap, self.r).snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), g.snapshot())

    def test_mega_is_four_total_actions_and_fifth_rejected_without_mutation(self):
        g = self.game(board=('mega',))
        for n in range(4):
            self.assertTrue(self.attacks(g))
            self.attack(g)
            self.assertEqual(self.unit(g).attacks_this_turn, n + 1)
        before = g.snapshot()
        self.assertFalse(self.attacks(g))
        with self.assertRaises(IllegalAction): self.attack(g)
        self.assertEqual(g.snapshot(), before)
        self.check(g)

    def test_megawindfury_and_windfury_do_not_multiply_or_reset_consumed_count(self):
        g = self.game(board=('wind',), hand=('mega_grant', 'silence'))
        self.attack(g); self.attack(g)
        self.cast(g, 'mega_grant', self.unit(g).id)
        self.assertEqual(attack_limit(g.state, self.unit(g)), 4)
        self.attack(g); self.attack(g)
        self.cast(g, 'silence', self.unit(g).id)
        self.assertEqual(self.unit(g).attacks_this_turn, 4)
        self.assertFalse(self.attacks(g))
        self.check(g)

    def test_current_aura_loss_reduces_cap_and_copy_does_not_keep_aura_as_attachment(self):
        g = self.game(board=('plain', 'aura'), hand=('copy', 'kill'))
        self.attack(g); self.attack(g)
        self.cast(g, 'copy', self.unit(g).id)
        copy = self.unit(g, 2)
        self.assertIn(Keyword.MEGA_WINDFURY, copy.keywords)
        self.assertFalse(any(a.keyword == Keyword.MEGA_WINDFURY for a in copy.abilities))
        self.cast(g, 'kill', self.unit(g, 1).id)
        self.assertEqual(self.unit(g).attacks_this_turn, 2)
        self.assertFalse(self.attacks(g))
        self.assertNotIn(Keyword.MEGA_WINDFURY, g.state.entities[copy.id].keywords)
        self.check(g)

    def test_infinite_exceeds_four_and_finite_public_total_works(self):
        for card, total in (('infinite', 7), ('three', 3)):
            with self.subTest(card=card):
                g = self.game(board=(card,))
                for _ in range(total): self.attack(g)
                self.assertEqual(self.unit(g).attacks_this_turn, total)
                self.assertEqual(bool(self.attacks(g)), card == 'infinite')
                self.check(g)

    def test_cannot_attack_keeps_active_defender_and_retaliation(self):
        g = self.game(board=('blocked',), enemy=('plain',))
        self.assertTrue(self.unit(g).active)
        self.assertFalse(self.attacks(g))
        g.apply(EndTurn(1))
        g.apply(Attack(2, self.unit(g, player=2).id, self.unit(g).id))
        self.assertEqual((self.unit(g).damage, self.unit(g, player=2).damage), (1, 1))
        self.check(g)

    def test_no_hero_policy_blocks_charge_target_but_allows_minion(self):
        g = self.game(board=(), hand=('nohero',))
        self.cast(g, 'nohero')
        self.assertEqual({a.defender_id for a in self.attacks(g)}, {self.unit(g, player=2).id})
        with self.assertRaises(IllegalAction): self.attack(g)
        self.attack(g, self.unit(g, player=2).id)
        self.check(g)

    def test_weapon_infinite_and_no_hero_are_current_equipment_contributions(self):
        g = self.game(weapon='fool', hand=('equip',))
        hero = self.hero(g, 1)
        for _ in range(5): self.attack(g, self.unit(g, player=2).id, hero)
        self.assertEqual({a.defender_id for a in self.attacks(g, hero)}, {self.unit(g, player=2).id})
        self.cast(g, 'equip')
        self.assertFalse(self.attacks(g, hero))
        self.assertEqual(g.state.entities[hero].attacks_this_turn, 5)
        self.assertEqual(attack_limit(g.state, g.state.entities[hero]), 1)
        self.assertFalse(any(a.kind == 'attack_policy' for a in g.state.entities[hero].abilities))
        self.check(g)

    def test_weapon_wear_removes_policies_and_mega_weapon_has_four(self):
        g = self.game(weapon='fool')
        hero = self.hero(g, 1)
        for _ in range(8): self.attack(g, self.unit(g, player=2).id, hero)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[hero].attacks_this_turn, 8)
        self.assertEqual(attack_limit(g.state, g.state.entities[hero]), 1)
        self.check(g)
        h = self.game(weapon='megaweapon')
        for _ in range(4): self.attack(h, source=self.hero(h, 1))
        self.assertFalse(self.attacks(h, self.hero(h, 1)))
        self.check(h)

    def test_current_damage_condition_toggles_after_damage_and_heal(self):
        self.conditional('quartz', 'damage', 'gt', 0)
        g = self.game(board=('quartz',), hand=('hurt', 'heal'))
        self.assertTrue(self.attacks(g))
        self.cast(g, 'hurt', self.unit(g).id)
        self.assertFalse(self.attacks(g))
        self.cast(g, 'heal', self.unit(g).id)
        self.assertTrue(self.attacks(g))
        self.attack(g); self.check(g)

    def test_controller_armor_condition_is_live_not_cached_on_minion(self):
        self.conditional('golem', 'controller_armor', 'lt', 3)
        g = self.game(board=('golem',), hand=('armor', 'hurt'))
        self.assertFalse(self.attacks(g))
        self.cast(g, 'armor')
        self.assertTrue(self.attacks(g))
        self.cast(g, 'hurt', self.hero(g, 1))
        self.assertFalse(self.attacks(g))
        self.check(g)

    def test_controller_spell_damage_condition_follows_source_silence(self):
        self.conditional('watcher', 'controller_spell_damage', 'eq', 0)
        g = self.game(board=('watcher', 'mage'), hand=('silence',))
        self.assertTrue(self.attacks(g, self.unit(g).id))
        self.cast(g, 'silence', self.unit(g, 1).id)
        self.assertFalse(self.attacks(g, self.unit(g).id))
        self.check(g)

    def test_controller_public_hand_count_condition_updates_and_enemy_identity_is_irrelevant(self):
        self.conditional('runner', 'controller_hand_size', 'lt', 2)
        g = self.game(board=('runner',), hand=('armor', 'buff'), enemy_hand=('plain',))
        h = self.game(board=('runner',), hand=('armor', 'buff'), enemy_hand=('mega',))
        self.assertTrue(self.attacks(g))
        self.assertEqual(g.for_player(1).legal_actions(), h.for_player(1).legal_actions())
        self.cast(g, 'armor')
        self.assertFalse(self.attacks(g))
        self.check(g)

    def test_local_attack_condition_and_conjunction_are_pure(self):
        self.r.register_card(CardDefinition('conditional', 'conditional', CardType.MINION, attack=1, health=30,
            attack_policies=(AttackPolicySpec('cannot_attack', conditions=(
                AttackPolicyCondition('attack', 'lt', 2), AttackPolicyCondition('damage', 'eq', 0))),)))
        g = self.game(board=('conditional',), hand=('buff',))
        before = g.snapshot()
        self.assertFalse(self.attacks(g)); self.assertFalse(self.attacks(g))
        self.assertEqual(g.snapshot(), before)
        self.cast(g, 'buff', self.unit(g).id)
        self.assertTrue(self.attacks(g)); self.check(g)

    def test_dynamic_policy_silence_copy_transform_and_expiry_share_lifecycle(self):
        g = self.game(board=('plain',), hand=('block_grant', 'copy', 'base_copy', 'silence', 'transform'))
        original = self.unit(g).id
        self.cast(g, 'block_grant', original)
        self.cast(g, 'copy', original); self.cast(g, 'base_copy', original)
        self.assertEqual(sum(a.kind == 'attack_policy' for a in self.unit(g, 1).abilities), 1)
        self.assertEqual(sum(a.kind == 'attack_policy' for a in self.unit(g, 2).abilities), 0)
        self.assertNotEqual(next(a.id for a in self.unit(g).abilities if a.kind == 'attack_policy'),
                            next(a.id for a in self.unit(g, 1).abilities if a.kind == 'attack_policy'))
        self.cast(g, 'silence', original)
        self.assertTrue(self.attacks(g, original))
        self.cast(g, 'transform', self.unit(g, 1).id)
        self.assertFalse(any(a.kind == 'attack_policy' for a in self.unit(g, 1).abilities))
        self.check(g)
        h = self.game(board=('plain',), hand=('temp_block',))
        self.cast(h, 'temp_block', self.unit(h).id)
        self.assertFalse(self.attacks(h))
        h.apply(EndTurn(1)); h.apply(EndTurn(2))
        self.assertTrue(self.attacks(h)); self.check(h)

    def test_bounce_resets_grants_but_reinstalls_printed_policy(self):
        g = self.game(board=('plain', 'blocked'), hand=('block_grant', 'bounce', 'bounce'))
        plain, blocked = self.unit(g).id, self.unit(g, 1).id
        self.cast(g, 'block_grant', plain)
        self.cast(g, 'bounce', plain); self.cast(g, 'bounce', blocked)
        self.assertFalse(any(a.kind == 'attack_policy' for a in g.state.entities[plain].abilities))
        self.assertTrue(any(a.kind == 'attack_policy' for a in g.state.entities[blocked].abilities))
        self.check(g)

    def test_control_change_preserves_restriction_but_reads_new_controller_condition(self):
        self.conditional('golem', 'controller_armor', 'lt', 3, keywords=(Keyword.CHARGE,))
        g = self.game(hand=('armor', 'steal'), enemy=('golem',))
        self.cast(g, 'armor')
        target = self.unit(g, player=2).id
        self.cast(g, 'steal', target)
        self.assertTrue(self.attacks(g, target))
        self.assertEqual(g.state.entities[target].owner, 2)
        self.check(g)

    def test_freeze_uses_current_shared_max_and_restrictions_without_spending(self):
        for card, enemy, used, deadline in (
                ('mega', ('plain',), 3, 1), ('mega', ('plain',), 4, 2),
                ('infinite', ('plain',), 5, 1), ('blocked', ('plain',), 0, 2),
                ('nohero', (), 0, 2), ('nohero', ('plain',), 0, 1)):
            with self.subTest(card=card, enemy=enemy, used=used):
                g = self.game(board=(card,), hand=('freeze',), enemy=enemy)
                for _ in range(used): self.attack(g)
                self.cast(g, 'freeze', self.unit(g).id)
                self.assertEqual(self.unit(g).frozen_until_owner_turn, deadline)
                self.assertEqual(self.unit(g).attacks_this_turn, used)
                self.check(g)

    def test_titan_mega_three_abilities_then_one_attack_and_cant_attack_does_not_disable_ability(self):
        for n in range(3): self.r.register_behavior(f'a{n}', lambda c: [GainArmor(c.player_id, 1)])
        self.r.register_card(CardDefinition('titan', 'titan', CardType.MINION, attack=1, health=30,
            keywords=(Keyword.TITAN, Keyword.MEGA_WINDFURY),
            activated_abilities=tuple(ActivatedAbilitySpec(f'a{n}', f'a{n}') for n in range(3))))
        g = self.game(hand=('titan', 'block_grant', 'silence'))
        self.cast(g, 'titan')
        source = self.unit(g).id
        for n in range(3): g.apply(UseMinionAbility(1, source, f'a{n}'))
        self.attack(g)
        self.assertEqual(self.unit(g).attacks_this_turn, 4)
        self.assertFalse(self.attacks(g)); self.check(g)
        h = self.game(board=('titan',), hand=('block_grant', 'freeze'))
        self.cast(h, 'block_grant', self.unit(h).id)
        h.apply(UseMinionAbility(1, self.unit(h).id, 'a0'))
        self.cast(h, 'freeze', self.unit(h).id)
        self.assertEqual(self.unit(h).frozen_until_owner_turn, 1)
        self.check(h)

    def test_forced_combat_keeps_existing_policy_bypass_and_count(self):
        self.spell('force', lambda c: [ForceAttack(self.unit_from(c).id, c.state.players[2].hero_id)])
        g = self.game(board=('blocked',), hand=('freeze', 'force'))
        self.cast(g, 'freeze', self.unit(g).id)
        self.cast(g, 'force')
        self.assertEqual(self.unit(g).attacks_this_turn, 0)
        self.assertEqual(g.state.entities[self.hero(g)].damage, 1)
        self.check(g)

    @staticmethod
    def unit_from(c):
        return c.state.entities[c.state.players[c.player_id].board[0]]

    def test_accepted_attack_is_not_revalidated_after_new_restriction(self):
        self.r.register_behavior('reaction', lambda c: [GrantAttackPolicy(c.event.source_id, AttackPolicySpec('cannot_attack'))])
        self.r.register_card(CardDefinition('listener', 'listener', CardType.MINION, attack=1, health=30,
            triggers=(TriggerSpec('attack_declared', 'reaction'),)))
        g = self.game(board=('mega',), enemy=('listener',))
        result = self.attack(g)
        self.assertTrue(any(e.kind == 'attack_finished' for e in result.events))
        self.assertEqual(g.state.entities[self.hero(g)].damage, 1)
        self.assertFalse(self.attacks(g)); self.check(g)

    def test_pending_choice_serializes_typed_grant_and_restores_identically(self):
        self.spell('choose', lambda c: [RequestChoice(c.player_id, (
            ChoiceOption('block', 'Block', effects=(GrantAttackPolicy(c.target_id, AttackPolicySpec('cannot_attack',
                conditions=(AttackPolicyCondition('damage', 'eq', 0),))),)),), source_id=c.source_id)], True)
        g = self.game(board=('plain',), hand=('choose',))
        self.cast(g, 'choose', self.unit(g).id)
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r)
        action = SelectChoice(1, g.state.pending_choice.id, ('block',))
        g.apply(action); restored.apply(action)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertFalse(self.attacks(g)); self.check(g)

    def test_policy_failure_rolls_back_attachments_counts_rng_and_information(self):
        self.spell('fail', lambda c: [GrantAttackPolicy(c.target_id, AttackPolicySpec('attacks_per_turn')), Unhandled()], True)
        g = self.game(board=('plain',), hand=('fail',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'fail', self.unit(g).id)
        self.assertEqual(g.snapshot(), before)

    def test_unknown_attributes_invalid_values_and_snapshot_policy_tampering_rejected(self):
        for build in (lambda: AttackPolicyCondition('unknown', 'eq', 0),
                      lambda: AttackPolicyCondition('attack', 'bad', 0),
                      lambda: AttackPolicyCondition('attack', 'eq', True),
                      lambda: AttackPolicySpec('attacks_per_turn', True),
                      lambda: AttackPolicySpec('cannot_attack', 2),
                      lambda: AttackPolicySpec('attacks_per_turn', 0),
                      lambda: AttackPolicySpec('unknown')):
            with self.assertRaises(ValueError): build()
        g = self.game(board=('blocked',))
        snapshot = deepcopy(g.snapshot())
        # Attack policies are current immutable ability payloads, not hidden callbacks.
        entity = snapshot['state']['entities'][str(self.unit(g).id)]
        ability = next(a for a in entity['abilities'] if a['kind'] == 'attack_policy')
        ability['attack_policy']['mode'] = 'unknown'
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
                                                 if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot, self.r)

    def test_mega_grants_to_weapon_use_existing_current_hero_projection(self):
        self.spell('weapon_mega', lambda c: [GrantKeyword(c.state.players[c.player_id].weapon_id, Keyword.MEGA_WINDFURY)])
        g = self.game(weapon='weapon', hand=('weapon_mega',))
        self.cast(g, 'weapon_mega')
        hero = self.hero(g, 1)
        self.assertIn(Keyword.MEGA_WINDFURY, g.state.entities[hero].keywords)
        for _ in range(4): self.attack(g, source=hero)
        self.assertFalse(self.attacks(g, hero))
        g.apply(EndTurn(1))
        self.assertNotIn(Keyword.MEGA_WINDFURY, g.state.entities[hero].keywords)
        self.check(g)

    def test_timed_mega_grant_keeps_usage_then_expires_at_controller_start(self):
        self.spell('timed_mega', lambda c: [GrantKeyword(c.target_id, Keyword.MEGA_WINDFURY,
            duration=TimedKeywordSpec(Keyword.MEGA_WINDFURY))], True)
        g = self.game(board=('plain',), hand=('timed_mega',))
        self.attack(g)
        self.cast(g, 'timed_mega', self.unit(g).id)
        self.assertEqual(self.unit(g).attacks_this_turn, 1)
        for _ in range(3): self.attack(g)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertNotIn(Keyword.MEGA_WINDFURY, self.unit(g).keywords)
        self.assertEqual(attack_limit(g.state, self.unit(g)), 1)
        self.check(g)

    def test_stored_mega_grant_survives_play_and_uses_four_after_summoning_sickness(self):
        self.spell('stored_mega', lambda c: [GrantStoredKeyword(CardReference.capture(next(
            c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == 'plain')), Keyword.MEGA_WINDFURY)])
        g = self.game(hand=('stored_mega', 'plain'))
        self.cast(g, 'stored_mega'); self.cast(g, 'plain')
        self.assertFalse(self.attacks(g))
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        for _ in range(4): self.attack(g)
        self.assertFalse(self.attacks(g)); self.check(g)

    def test_controller_spell_damage_includes_persistent_player_effect_and_freeze(self):
        self.conditional('watcher', 'controller_spell_damage', 'eq', 0)
        self.r.register_player_effect(PlayerEffectSpec('spell_bonus', 'armor', spell_damage=2))
        self.spell('gain_spell', lambda c: [AddPlayerEffect(c.player_id, 'spell_bonus', c.source_id)])
        g = self.game(board=('watcher',), hand=('gain_spell', 'freeze'))
        self.assertFalse(self.attacks(g))
        self.cast(g, 'gain_spell')
        self.assertTrue(self.attacks(g))
        self.cast(g, 'freeze', self.unit(g).id)
        self.assertEqual(self.unit(g).frozen_until_owner_turn, 1)
        with self.assertRaises(ValueError): attack_limit(g.state, self.unit(g))
        self.assertEqual(attack_limit(g.state, self.unit(g), self.r), 1)
        self.check(g)

    def test_player_port_lists_only_allowed_targets_and_successful_submission_consumes_one(self):
        g = self.game(board=('nohero',))
        port = g.for_player(1)
        listing = port.legal_actions()
        actions = [a for a in listing['actions'] if a['type'] == 'attack']
        self.assertEqual(len(actions), 1)
        result = port.submit({'revision': listing['revision'], 'action': actions[0]})
        self.assertTrue(result['accepted'])
        self.assertEqual(self.unit(g).attacks_this_turn, 1)
        self.check(g)

    def test_finite_max_and_mega_combine_by_max_and_granted_infinite_expires(self):
        self.spell('three_grant', lambda c: [GrantAttackPolicy(c.target_id, AttackPolicySpec('attacks_per_turn', 3))], True)
        self.spell('infinite_grant', lambda c: [GrantAttackPolicy(c.target_id,
            AttackPolicySpec('attacks_per_turn'), expires_turn=c.state.turn)], True)
        g = self.game(board=('mega',), hand=('three_grant', 'infinite_grant'))
        self.cast(g, 'three_grant', self.unit(g).id)
        self.assertEqual(attack_limit(g.state, self.unit(g)), 4)
        self.cast(g, 'infinite_grant', self.unit(g).id)
        for _ in range(6): self.attack(g)
        self.assertIsNone(attack_limit(g.state, self.unit(g)))
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(attack_limit(g.state, self.unit(g)), 4)
        self.check(g)

    def test_current_no_hero_grant_does_not_remove_existing_taunt_constraint(self):
        self.r.register_card(CardDefinition('taunt', 'taunt', CardType.MINION, attack=1, health=30,
                                            keywords=(Keyword.TAUNT,)))
        self.spell('nohero_grant', lambda c: [GrantAttackPolicy(c.target_id, AttackPolicySpec('cannot_attack_heroes'))], True)
        g = self.game(board=('mega',), enemy=('plain', 'taunt'), hand=('nohero_grant',))
        self.cast(g, 'nohero_grant', self.unit(g).id)
        self.assertEqual({a.defender_id for a in self.attacks(g)}, {self.unit(g, 1, 2).id})
        self.attack(g, self.unit(g, 1, 2).id)
        self.check(g)

    def test_frozen_current_copy_uses_final_position_charge_and_mega_aura_for_deadline(self):
        self.r.register_card(CardDefinition('charge_mega_aura', 'charge_mega_aura', CardType.MINION,
            attack=1, health=4, keyword_auras=(
                KeywordAuraSpec(Keyword.CHARGE, 'friendly_minions'),
                KeywordAuraSpec(Keyword.MEGA_WINDFURY, 'friendly_minions'))))
        g = self.game(board=('plain', 'charge_mega_aura'), hand=('freeze', 'copy'))
        source = self.unit(g).id
        self.cast(g, 'freeze', source)
        self.assertEqual(g.state.entities[source].frozen_until_owner_turn, 1)
        self.cast(g, 'copy', source)
        copied = self.unit(g, 2)
        self.assertTrue({Keyword.CHARGE, Keyword.MEGA_WINDFURY} <= copied.keywords)
        self.assertEqual(copied.summoned_turn, g.state.turn)
        self.assertEqual(copied.attacks_this_turn, 0)
        self.assertEqual(copied.frozen_until_owner_turn, 1)
        self.assertFalse(self.attacks(g, copied.id))
        g.apply(EndTurn(1))
        self.assertIsNone(g.state.entities[copied.id].frozen_until_owner_turn)
        self.check(g)


if __name__ == '__main__':
    unittest.main()
