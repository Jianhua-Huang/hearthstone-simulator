"""Public board-count policies, with explicit local presence contracts."""
from copy import deepcopy
import json
import unittest

from tests import test_v119_attack_policies as fixtures
from hs_sim.engine import (ActivatedAbilitySpec, AttackPolicyCondition, AttackPolicySpec,
    CardDefinition, CardType, Game, GrantAttackPolicy, IllegalAction, Keyword,
    ResolutionError, SelectChoice, SnapshotError, TriggerSpec, UseMinionAbility)
from hs_sim.engine.attack_policies import attack_limit, current_policies
from hs_sim.engine.effects import (ChoiceOption, GainArmor, RequestChoice, Summon)
from hs_sim.engine.serialization import canonical_hash


class AttackBoardCountTests(unittest.TestCase):
    setUp = fixtures.AttackPolicyTests.setUp
    spell = fixtures.AttackPolicyTests.spell
    game = fixtures.AttackPolicyTests.game
    unit = fixtures.AttackPolicyTests.unit
    hero = fixtures.AttackPolicyTests.hero
    cast = fixtures.AttackPolicyTests.cast
    attack = fixtures.AttackPolicyTests.attack
    attacks = fixtures.AttackPolicyTests.attacks
    check = fixtures.AttackPolicyTests.check

    def condition(self, scope='both', presence='board_present', comparison='ne', value=1):
        return AttackPolicyCondition('battlefield_minion_count', comparison, value,
                                     board_scope=scope, board_presence=presence)

    def counted(self, name='counted', *, condition=None, **fields):
        self.r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=30,
            attack_policies=(AttackPolicySpec('cannot_attack', conditions=(condition or self.condition(),)),),
            **fields))

    def test_both_battlefields_must_be_unique_and_recount_after_actual_death(self):
        self.counted()
        g = self.game(board=('counted',), hand=('kill',))
        self.assertFalse(self.attacks(g))
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.attack(g)
        self.assertEqual(g.snapshot(), before)
        self.cast(g, 'kill', self.unit(g, player=2).id)
        self.assertTrue(self.attacks(g))
        self.attack(g)
        self.check(g)

    def test_friendly_opponent_and_both_are_distinct_declared_scopes(self):
        expected = {'friendly': True, 'opponent': True, 'both': False}
        for scope in expected: self.counted(scope, condition=self.condition(scope))
        for scope in expected:
            with self.subTest(scope=scope):
                g = self.game(board=(scope,))
                self.assertEqual(bool(self.attacks(g)), expected[scope])
                self.check(g)

    def test_location_and_both_heroes_do_not_count_as_minions(self):
        self.counted()
        self.r.register_behavior('noop', lambda c: [])
        self.r.register_card(CardDefinition('place', 'place', CardType.LOCATION, durability=2, on_use='noop'))
        g = self.game(board=('counted', 'place'), enemy=('place',))
        self.assertTrue(self.attacks(g))
        self.attack(g)
        self.check(g)

    def test_dormant_presence_is_explicit_not_silently_filtered(self):
        self.r.register_card(CardDefinition('sleeping', 'sleeping', CardType.MINION,
                                           attack=1, health=30, dormant_turns=2))
        for presence in ('board_present', 'live', 'active'):
            self.counted(presence, condition=self.condition(presence=presence))
        for presence, can_attack in (('board_present', False), ('live', False), ('active', True)):
            with self.subTest(presence=presence):
                g = self.game(board=(presence, 'sleeping'), enemy=())
                self.assertEqual(bool(self.attacks(g)), can_attack)
                self.check(g)

    def test_unsettled_dead_and_doomed_presence_policy_queries_are_pure(self):
        self.counted('present', condition=self.condition(presence='board_present'))
        self.counted('live', condition=self.condition(presence='live'))
        for card in ('present', 'live'):
            g = self.game(board=(card,))
            for fatal_kind in ('health', 'doomed'):
                state = deepcopy(g.state)
                target = state.entities[state.players[2].board[0]]
                if fatal_kind == 'health': target.damage = target.max_health
                else: target.doomed = True
                before = deepcopy(state)
                policy = current_policies(state, state.entities[self.unit(g).id], self.r)
                self.assertEqual(bool(policy), card == 'present')
                self.assertEqual(state, before)

    def test_scope_reads_new_controller_after_steal_not_original_owner(self):
        self.counted(condition=self.condition('friendly', comparison='ge', value=2),
                     keywords=(Keyword.CHARGE,))
        g = self.game(board=('plain', 'plain'), hand=('steal',), enemy=('counted',))
        source = self.unit(g, player=2)
        self.assertFalse(current_policies(g.state, source, self.r))
        self.cast(g, 'steal', source.id)
        source = g.state.entities[source.id]
        self.assertEqual(source.owner, 2)
        self.assertEqual(source.controller, 1)
        self.assertTrue(current_policies(g.state, source, self.r))
        self.assertFalse(self.attacks(g, source.id))
        self.check(g)

    def test_current_weapon_count_policy_changes_cap_without_resetting_used(self):
        self.r.register_card(CardDefinition('count_weapon', 'count_weapon', CardType.WEAPON,
            attack=1, durability=8, attack_policies=(AttackPolicySpec('attacks_per_turn', 3,
                conditions=(self.condition('friendly', comparison='eq', value=1),)),)))
        g = self.game(board=('plain',), hand=('kill',), enemy=(), weapon='count_weapon')
        hero = self.hero(g, 1)
        self.assertEqual(attack_limit(g.state, g.state.entities[hero], self.r), 3)
        for _ in range(3): self.attack(g, source=hero)
        self.cast(g, 'kill', self.unit(g).id)
        self.assertEqual(attack_limit(g.state, g.state.entities[hero], self.r), 1)
        self.assertEqual(g.state.entities[hero].attacks_this_turn, 3)
        self.assertFalse(self.attacks(g, hero))
        self.check(g)

    def test_dynamic_current_copy_keeps_count_policy_base_copy_and_silence_do_not(self):
        self.spell('grant_count', lambda c: [GrantAttackPolicy(c.target_id,
            AttackPolicySpec('cannot_attack', conditions=(self.condition(),)))], True)
        g = self.game(board=('plain',), hand=('grant_count', 'copy', 'base_copy', 'silence'), enemy=())
        original = self.unit(g).id
        self.cast(g, 'grant_count', original)
        self.assertTrue(self.attacks(g, original))
        self.cast(g, 'copy', original)
        copied = self.unit(g, 1).id
        self.assertTrue(current_policies(g.state, g.state.entities[copied], self.r))
        self.assertFalse(self.attacks(g, original))
        self.cast(g, 'base_copy', original)
        self.assertFalse(current_policies(g.state, self.unit(g, 2), self.r))
        self.cast(g, 'silence', original)
        self.assertFalse(current_policies(g.state, g.state.entities[original], self.r))
        self.assertTrue(self.attacks(g, original))
        self.check(g)

    def test_accepted_attack_finishes_after_new_count_and_real_waiting_choice(self):
        self.r.register_behavior('count_reaction', lambda c: [
            Summon(2, 'plain'), RequestChoice(1, (ChoiceOption('continue', 'Continue'),), source_id=c.source_id)])
        self.counted(keywords=(Keyword.MEGA_WINDFURY,),
                     triggers=(TriggerSpec('attack_declared', 'count_reaction'),))
        g = self.game(board=('counted',), enemy=())
        self.assertTrue(self.attacks(g))
        self.attack(g)
        self.assertIsNotNone(g.state.pending_choice)
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r)
        self.check(g)
        action = SelectChoice(1, g.state.pending_choice.id, ('continue',))
        g.apply(action)
        restored.apply(action)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.entities[self.hero(g)].damage, 1)
        self.assertEqual(self.unit(g).attacks_this_turn, 1)
        self.assertFalse(self.attacks(g))
        self.check(g)

    def test_freeze_clock_uses_the_selected_count_presence_without_spending(self):
        self.r.register_card(CardDefinition('sleeping', 'sleeping', CardType.MINION,
                                           attack=1, health=30, dormant_turns=2))
        for presence in ('board_present', 'active'):
            self.counted(presence, condition=self.condition(presence=presence))
        for presence, deadline in (('board_present', 2), ('active', 1)):
            g = self.game(board=(presence, 'sleeping'), hand=('freeze',), enemy=())
            self.cast(g, 'freeze', self.unit(g).id)
            self.assertEqual(self.unit(g).frozen_until_owner_turn, deadline)
            self.assertEqual(self.unit(g).attacks_this_turn, 0)
            self.check(g)

    def test_titan_can_use_abilities_while_count_blocks_attacks_then_attack_when_unique(self):
        for n in range(3): self.r.register_behavior(f'count_a{n}', lambda c: [GainArmor(c.player_id, 1)])
        self.counted('count_titan', keywords=(Keyword.TITAN, Keyword.MEGA_WINDFURY),
            activated_abilities=tuple(ActivatedAbilitySpec(f'count_a{n}', f'count_a{n}') for n in range(3)))
        g = self.game(board=('count_titan', 'plain'), hand=('kill',), enemy=())
        actor = self.unit(g).id
        for n in range(3): g.apply(UseMinionAbility(1, actor, f'count_a{n}'))
        self.assertFalse(self.attacks(g, actor))
        self.cast(g, 'kill', self.unit(g, 1).id)
        self.assertTrue(self.attacks(g, actor))
        self.attack(g, source=actor)
        self.assertEqual(self.unit(g).attacks_this_turn, 4)
        self.check(g)

    def test_enemy_hidden_card_identity_is_irrelevant_to_player_legal_actions(self):
        self.counted()
        for name in ('hidden_marker_a', 'hidden_marker_b'): self.spell(name, lambda c: [])
        g = self.game(board=('counted',), enemy=(), enemy_hand=('hidden_marker_a',))
        h = self.game(board=('counted',), enemy=(), enemy_hand=('hidden_marker_b',))
        listing = g.for_player(1).legal_actions()
        self.assertEqual(listing, h.for_player(1).legal_actions())
        self.assertNotIn('hidden_marker_', json.dumps(listing))
        self.assertNotIn('board_presence', json.dumps(listing))
        action = next(a for a in listing['actions'] if a['type'] == 'attack')
        result = g.for_player(1).submit({'revision': listing['revision'], 'action': action})
        self.assertTrue(result['accepted'])
        self.assertEqual(self.unit(g).attacks_this_turn, 1)
        self.check(g)

    def test_unknown_or_misplaced_policies_and_tampered_snapshot_are_rejected(self):
        for build in (lambda: AttackPolicyCondition('battlefield_minion_count', 'eq', 1),
                      lambda: self.condition(scope='unknown'),
                      lambda: self.condition(presence='unknown'),
                      lambda: AttackPolicyCondition('attack', 'eq', 1, board_scope='both'),
                      lambda: AttackPolicyCondition('health', 'eq', 1, board_presence='live')):
            with self.assertRaises(ValueError): build()
        self.counted()
        g = self.game(board=('counted',), enemy=())
        snapshot = deepcopy(g.snapshot())
        entity = snapshot['state']['entities'][str(self.unit(g).id)]
        ability = next(a for a in entity['abilities'] if a['kind'] == 'attack_policy')
        ability['attack_policy']['conditions'][0]['board_presence'] = 'unknown'
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot, self.r)

    def test_unknown_later_effect_rolls_back_count_grant_and_all_state(self):
        self.spell('count_fail', lambda c: [GrantAttackPolicy(c.target_id,
            AttackPolicySpec('cannot_attack', conditions=(self.condition(),))), fixtures.Unhandled()], True)
        g = self.game(board=('plain',), hand=('count_fail',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'count_fail', self.unit(g).id)
        self.assertEqual(g.snapshot(), before)
