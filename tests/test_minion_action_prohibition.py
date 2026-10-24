"""Hard action restrictions on real C'Thun, distinct from ability producers."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.empire_cthun_cards import FAMILY
from hs_sim.engine import (ActivatedAbilitySpec, AttackPolicySpec, CardDefinition,
    CardType, EndTurn, Game, Keyword, PlayerSetup, Scenario, SnapshotError,
    UseMinionAbility)
from hs_sim.engine.ability_families import completed_ids
from hs_sim.engine.attack_policies import GrantAttackPolicy, current_policies
from hs_sim.engine.effects import Freeze, SetStats
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.minion_abilities import remaining_abilities
from hs_sim.engine.model import SpellSchool
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.turn_scheduling import QueueTurns
from hs_sim.targets import canonical_digest
from card_batch_testkit import CardBatchTestMixin

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/support/minion-action-prohibition-v1.json'
PIN = '6064224c0daf1be07f1c765e9a74078399f93d2c64adaad3093ea911bc2ef156'
CHAINS, GOD, DEACON = 'CATA_496', 'BE_013', 'BE_012'
SKILLS = tuple('BE_013t' + str(n) for n in range(1, 5))
P = 'fixture.minion_action_prohibition.'


@lru_cache(maxsize=1)
def packet():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Minion action source packet changed')
    if tuple(row['record']['id'] for row in data['records']) != (CHAINS, GOD, DEACON, *SKILLS):
        raise ValueError('Unreviewed minion action source set')
    for row in data['records']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise ValueError('Incomplete native source record')
    return data


@lru_cache(maxsize=None)
def fixture(mode=None, role='writer'):
    if mode is not None or role not in ('writer', 'independent-reader'):
        raise ValueError('Unknown minion action fixture')
    packet()
    registry = build_registry()
    scripts = {
        'block': lambda c: (GrantAttackPolicy(c.target_id, AttackPolicySpec('cannot_attack_or_use_minion_abilities'),
            c.source_id, expires_turn=c.state.turn),),
        'zero_hero_only': lambda c: (SetStats(c.target_id, attack=0, source_id=c.source_id),
            GrantAttackPolicy(c.target_id, AttackPolicySpec('cannot_attack_heroes'), c.source_id),
            GrantAttackPolicy(c.target_id, AttackPolicySpec('cannot_attack'), c.source_id)),
        'extra': lambda c: (QueueTurns((1,), c.source_id),),
        'freeze': lambda c: (Freeze(c.target_id),),
        'shadow': lambda c: (),
        'noop': lambda c: (),
    }
    for name, body in scripts.items():
        registry.register_behavior(P + name, body)
        if name != 'noop':
            registry.register_card(CardDefinition(P + name, name, CardType.SPELL,
                on_play=P + name, requires_target=name in ('block', 'zero_hero_only', 'freeze'),
                spell_school=SpellSchool.SHADOW if name == 'shadow' else None))
    # Diagnostic carrier checks the same gate without adding a Wild card to the target.
    registry.register_card(CardDefinition(P + 'titan', 'Diagnostic Titan', CardType.MINION,
        health=9, keywords=(Keyword.TITAN,), activated_abilities=tuple(
            ActivatedAbilitySpec('a' + str(n), P + 'noop') for n in range(1, 4))))
    registry._version = 'minion-action-prohibition-v2'
    registry.validate()
    registry.freeze()
    return registry


class MinionActionProhibitionTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), *, own=False, card=GOD):
        self.mode = None
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_07', board=(card,) if own else (), hand=hand,
                deck=('CORE_CS2_182',) * 8, mana=10, max_mana=10),
            PlayerSetup('HERO_11', board=() if own else (card,),
                deck=('CORE_CS2_182',) * 8, mana=10, max_mana=10)), seed=5331),
            fixture(None, 'writer'))

    def steal(self, game):
        entity_id = self.entity(game, GOD, player=2, zone='board').id
        self.play(game, CHAINS, entity_id)
        self.assertEqual(game.state.entities[entity_id].controller, 1)
        self.assertEqual(game.state.players[1].mana, 8)
        self.assertTrue(any(p.mode == 'cannot_attack_or_use_minion_abilities' for p in
            current_policies(game.state, game.state.entities[entity_id], game.registry)))
        return entity_id

    def assert_blocked(self, game, entity_id, ability_id):
        saved = game.snapshot()
        with self.assertRaisesRegex(IllegalAction, 'No minion ability action available'):
            game.apply(UseMinionAbility(1, entity_id, ability_id))
        self.assertEqual(game.snapshot(), saved)
        self.assertFalse(any(isinstance(a, UseMinionAbility) and a.entity_id == entity_id
            for a in game.legal_actions()))
        self.assertFalse(any(a['type'] == 'use_minion_ability'
            for a in game.for_player(1).legal_actions()['actions']))
        self.assertEqual(game.snapshot(), saved)

    def test_real_chains_blocks_cthun_free_skill_without_consumption_or_rng_change(self):
        game = self.game((CHAINS,))
        entity_id = self.steal(game)
        source = game.state.entities[entity_id]
        self.assertFalse(source.old_god_free_used)
        self.assertEqual((source.attacks_this_turn, len(remaining_abilities(source))), (0, 4))
        self.assert_blocked(game, entity_id, SKILLS[0])
        restored = self.portable(game)
        self.assert_blocked(restored, entity_id, SKILLS[0])

    def test_hard_gate_also_blocks_paid_opportunity_and_player_submission(self):
        game = self.game((P + 'block',), own=True)
        entity_id = self.entity(game, GOD, zone='board').id
        game.apply(UseMinionAbility(1, entity_id, SKILLS[0]))
        self.assertTrue(game.state.entities[entity_id].old_god_free_used)
        self.assertEqual(game.state.entities[entity_id].attacks_this_turn, 0)
        port = game.for_player(1)
        command = next(a for a in port.legal_actions()['actions']
            if a['type'] == 'use_minion_ability' and a['ability_id'] == SKILLS[3])
        self.play(game, P + 'block', entity_id)
        self.assert_blocked(game, entity_id, SKILLS[3])
        saved = game.snapshot()
        result = port.submit({'revision': port.legal_actions()['revision'], 'action': command})
        self.assertFalse(result['accepted'])
        self.assertEqual(game.snapshot(), saved)
        self.portable(game)

    def test_zero_attack_and_attack_only_restrictions_preserve_native_skill_budget(self):
        game = self.game((P + 'zero_hero_only',), own=True)
        entity_id = self.entity(game, GOD, zone='board').id
        self.play(game, P + 'zero_hero_only', entity_id)
        self.assertEqual(game.state.entities[entity_id].attack, 0)
        self.assertEqual(tuple(p.mode for p in current_policies(game.state,
            game.state.entities[entity_id], game.registry)), ('cannot_attack_heroes', 'cannot_attack'))
        game.apply(UseMinionAbility(1, entity_id, SKILLS[0]))
        self.assertEqual(game.state.entities[entity_id].attacks_this_turn, 0)
        game.apply(UseMinionAbility(1, entity_id, SKILLS[3]))
        self.assertEqual(game.state.entities[entity_id].attacks_this_turn, 1)
        self.assert_blocked(game, entity_id, SKILLS[1])
        self.portable(game)

    def test_native_ban_expires_before_original_return_clock_and_restored_actions_continue(self):
        game = self.game((CHAINS, P + 'extra'))
        entity_id = self.steal(game)
        self.play(game, P + 'extra')
        self.assert_blocked(game, entity_id, SKILLS[0])
        restored = self.portable(game)
        for current in (game, restored):
            current.apply(EndTurn(1))
            self.assertEqual(current.state.active_player, 1)
            self.assertEqual(current.state.entities[entity_id].controller, 1)
            self.assertFalse(any(p.mode == 'cannot_attack_or_use_minion_abilities' for p in
                current_policies(current.state, current.state.entities[entity_id], current.registry)))
            current.apply(UseMinionAbility(1, entity_id, SKILLS[0]))
            current.apply(UseMinionAbility(1, entity_id, SKILLS[3]))
            self.assertEqual(current.state.entities[entity_id].attacks_this_turn, 1)
            current.apply(EndTurn(1))
            self.assertEqual(current.state.active_player, 2)
            current.apply(EndTurn(2))
            self.assertEqual(current.state.entities[entity_id].controller, 2)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.portable(game)

    def test_native_deacon_external_skill_remains_independent_of_blocked_physical_god(self):
        game = self.game((CHAINS, DEACON, P + 'shadow'))
        entity_id = self.steal(game)
        self.play(game, P + 'shadow')
        self.play(game, DEACON)
        self.assertIsNotNone(game.state.pending_choice)
        restored = self.portable(game)
        for current in (game, restored):
            self.choose(current, SKILLS[1])
            self.assertEqual(completed_ids(current.state,
                current.registry.ability_family_profiles[FAMILY], 1), (SKILLS[1],))
            source = current.state.entities[entity_id]
            self.assertEqual((source.old_god_free_used, source.attacks_this_turn,
                len(remaining_abilities(source))), (False, 0, 4))
            self.assert_blocked(current, entity_id, SKILLS[0])
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.portable(game)

    def test_stealing_frozen_native_god_rebinds_clock_after_action_lock_is_installed(self):
        game = self.game((CHAINS, P + 'freeze', P + 'extra'))
        entity_id = self.entity(game, GOD, player=2, zone='board').id
        self.play(game, P + 'freeze', entity_id)
        self.steal(game)
        self.assertEqual(game.state.entities[entity_id].frozen_until_owner_turn, 2)
        self.play(game, P + 'extra')
        restored = self.portable(game)
        for current in (game, restored):
            current.apply(EndTurn(1))
            self.assertEqual(current.state.active_player, 1)
            self.assertTrue(current.state.entities[entity_id].frozen)
            self.assert_blocked(current, entity_id, SKILLS[0])
            current.apply(EndTurn(1))
            self.assertFalse(current.state.entities[entity_id].frozen)
            current.apply(EndTurn(2))
            self.assertEqual(current.state.entities[entity_id].controller, 2)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.portable(game)

    def test_shared_titan_gate_expires_without_changing_original_action_budget(self):
        game = self.game((P + 'block',), own=True, card=P + 'titan')
        entity_id = self.entity(game, P + 'titan', zone='board').id
        self.assertEqual(game.state.entities[entity_id].attack, 0)
        self.assertTrue(any(isinstance(a, UseMinionAbility) for a in game.legal_actions()))
        self.play(game, P + 'block', entity_id)
        self.assert_blocked(game, entity_id, 'a1')
        game.apply(EndTurn(1))
        game.apply(EndTurn(2))
        game.apply(UseMinionAbility(1, entity_id, 'a1'))
        self.assertEqual(game.state.entities[entity_id].attacks_this_turn, 1)
        self.assert_blocked(game, entity_id, 'a2')
        self.portable(game)

    def test_hard_ban_is_no_current_action_when_freeze_deadline_is_captured(self):
        game = self.game((P + 'block', P + 'freeze'), own=True)
        entity_id = self.entity(game, GOD, zone='board').id
        self.play(game, P + 'block', entity_id)
        self.play(game, P + 'freeze', entity_id)
        game.apply(EndTurn(1))
        self.assertTrue(game.state.entities[entity_id].frozen)
        game.apply(EndTurn(2))
        self.assertTrue(game.state.entities[entity_id].frozen)
        self.assert_blocked(game, entity_id, SKILLS[0])
        game.apply(EndTurn(1))
        self.assertFalse(game.state.entities[entity_id].frozen)
        game.apply(EndTurn(2))
        game.apply(UseMinionAbility(1, entity_id, SKILLS[0]))
        self.assertTrue(game.state.entities[entity_id].old_god_free_used)
        self.portable(game)

    def test_previous_core_cannot_restore_even_with_same_schema_and_valid_hashes(self):
        game = self.game((CHAINS,))
        self.steal(game)
        saved = deepcopy(game.snapshot())
        self.assertEqual(saved['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(saved['mechanics_version']['version'], CORE_EFFECTS_VERSION)
        saved['mechanics_version']['version'] = 'core-effects-v730'
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, 'Mechanics version mismatch'):
            Game.from_snapshot(saved, fixture(None, 'independent-reader'))


if __name__ == '__main__':
    unittest.main()
