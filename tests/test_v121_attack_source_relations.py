"""Original physical-source policies; isolated internal evidence, not ETC CN calibration."""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import unittest

import hs_sim
from hs_sim.engine import (Attack, AttackPolicySpec, AttackSourceBinding, AttackSourcePolicy,
    BoardPresenceReference, CardClass, CardDefinition, CardReference, CardType, Game,
    GrantAttackPolicy, IllegalAction, Keyword, LaunchStarship, PlayCard, PlayerSetup,
    Registry, ResolutionError, Scenario, SelectChoice, SnapshotError, SummonStoredCard,
    TriggerSpec, Zone)
from hs_sim.engine.attack_policies import attack_limit, current_policies
from hs_sim.engine.board_presence import attack_source_enabled
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    Effect, EquipWeapon, Freeze, GainArmor, RandomDamage, RequestChoice, ReturnToHand,
    ShuffleIntoDeck, Silence, Summon, Transform)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction
from hs_sim.engine.summon_sources import ResurrectMinion


@dataclass(frozen=True)
class Unhandled(Effect):
    pass


LIVE = AttackSourcePolicy('live', 'preserve', 'ignore')


class AttackSourceRelationTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(Path(hs_sim.__file__).resolve(), Path(__file__).resolve().parents[1] / 'hs_sim/__init__.py')
        self.r = Registry('isolated-original-physical-attack-source')
        self.r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=100))
        for card in ('source', 'plain', 'form', 'other'):
            self.r.register_card(CardDefinition(card, card, CardType.MINION, attack=1, health=20,
                                                keywords=(Keyword.CHARGE,)))
        self.spell('bind', lambda c: [self.bound(c)], True)
        self.spell('kill', lambda c: [Destroy(c.target_id)], True)
        self.spell('silence', lambda c: [Silence(c.target_id)], True)
        self.spell('transform', lambda c: [Transform(c.target_id, 'form')], True)
        self.spell('reverse', lambda c: [Transform(c.target_id, 'source')], True)
        self.spell('bounce', lambda c: [ReturnToHand(c.target_id)], True)
        self.spell('shuffle', lambda c: [ShuffleIntoDeck(c.target_id)], True)
        self.spell('copy', lambda c: [CopyMinion(c.target_id, c.player_id)], True)
        self.spell('basecopy', lambda c: [CopyMinion(c.target_id, c.player_id, mode='base')], True)
        self.spell('steal', lambda c: [ChangeControl(c.target_id, c.player_id)], True)
        self.spell('dormant', lambda c: [MakeDormant(c.target_id, None)], True)
        self.spell('awaken', lambda c: [AwakenMinion(self.source(c))])
        self.spell('freeze', lambda c: [Freeze(c.target_id)], True)
        self.spell('summon', lambda c: [Summon(c.player_id, 'source')])

    def spell(self, name, behavior, targeted=False):
        self.r.register_behavior(name, behavior)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, requires_target=targeted))

    @staticmethod
    def source(c):
        return c.state.players[c.player_id].board[0]

    def bound(self, c, policy=LIVE, source_id=None, target_id=None):
        source_id = source_id if source_id is not None else self.source(c)
        binding = AttackSourceBinding.capture(c.state, source_id, policy)
        return GrantAttackPolicy(target_id or c.target_id, AttackPolicySpec('cannot_attack'),
                                 source_id=source_id, source_binding=binding)

    def game(self, board=('source', 'plain'), hand=(), enemy=('plain',), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', board=board, hand=hand, deck=('other',) * 5, mana=10, max_mana=10),
            PlayerSetup('hero', board=enemy, hand=enemy_hand, deck=('other',) * 5, mana=10, max_mana=10)), seed=27), self.r)

    def unit(self, g, pos=0, player=1):
        return g.state.entities[g.state.players[player].board[pos]]

    def cast(self, g, name, target=None):
        player = g.state.active_player
        entity_id = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(player, entity_id, target))

    def attacks(self, g, target_id):
        return [a for a in g.legal_actions() if isinstance(a, Attack) and a.attacker_id == target_id]

    def binding(self, g, target_id):
        return next(a.attack_source_binding for a in g.state.entities[target_id].abilities if a.kind == 'attack_policy')

    def check(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, self.r).snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), g.snapshot())

    def test_original_source_blocks_submission_and_enumeration_then_death_releases(self):
        g = self.game(hand=('bind', 'kill'))
        source, target = self.unit(g).id, self.unit(g, 1).id
        self.cast(g, 'bind', target)
        self.assertFalse(self.attacks(g, target))
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(Attack(1, target, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), before)
        self.cast(g, 'kill', source)
        self.assertIsNone(g.state.entities[source].board_presence_id)
        self.assertTrue(self.attacks(g, target))
        self.check(g)

    def test_same_name_source_copy_does_not_substitute_for_original(self):
        g = self.game(hand=('bind', 'copy', 'kill'))
        source, target = self.unit(g).id, self.unit(g, 1).id
        self.cast(g, 'bind', target)
        old = self.binding(g, target)
        self.cast(g, 'copy', source)
        clone = self.unit(g, 2)
        self.assertNotEqual(clone.board_presence_id, old.reference.presence_id)
        self.cast(g, 'kill', source)
        self.assertTrue(self.attacks(g, target))
        self.assertEqual(self.binding(g, target), old)
        self.check(g)

    def test_source_bounce_same_entity_reentry_never_reactivates_old_segment(self):
        g = self.game(hand=('bind', 'bounce'))
        source, target = self.unit(g).id, self.unit(g, 1).id
        self.cast(g, 'bind', target)
        old = self.binding(g, target)
        self.cast(g, 'bounce', source)
        self.assertTrue(self.attacks(g, target))
        g.apply(PlayCard(1, source))
        self.assertNotEqual(g.state.entities[source].board_presence_id, old.reference.presence_id)
        self.assertTrue(self.attacks(g, target))
        self.check(g)

    def test_source_transfer_preserves_segment_despite_new_controller_and_order(self):
        self.spell('foreign_bind', lambda c: [self.bound(c, source_id=c.state.players[2].board[0])], True)
        # The declared source is the enemy physical minion, not the casting spell.
        h = self.game(board=('plain',), hand=('foreign_bind', 'steal'), enemy=('source',))
        target, source = self.unit(h).id, self.unit(h, player=2).id
        self.cast(h, 'foreign_bind', target)
        old_presence, old_order = h.state.entities[source].board_presence_id, h.state.entities[source].entered_order
        self.cast(h, 'steal', source)
        self.assertEqual(h.state.entities[source].board_presence_id, old_presence)
        self.assertGreater(h.state.entities[source].entered_order, old_order)
        self.assertFalse(self.attacks(h, target))
        self.check(h)

    def test_source_transform_preserves_or_breaks_only_by_explicit_policy(self):
        for policy in (LIVE, AttackSourcePolicy('live', 'captured_epoch', 'ignore')):
            self.spell('bind_' + policy.transform, lambda c, p=policy: [self.bound(c, p)], True)
        for policy, blocked in ((LIVE, True), (AttackSourcePolicy('live', 'captured_epoch', 'ignore'), False)):
            with self.subTest(policy=policy):
                g = self.game(hand=('bind_' + policy.transform, 'transform', 'reverse'))
                source, target = self.unit(g).id, self.unit(g, 1).id
                self.cast(g, 'bind_' + policy.transform, target)
                presence = g.state.entities[source].board_presence_id
                self.cast(g, 'transform', source)
                self.assertEqual(g.state.entities[source].board_presence_id, presence)
                self.assertEqual(not bool(self.attacks(g, target)), blocked)
                self.cast(g, 'reverse', source)
                self.assertEqual(not bool(self.attacks(g, target)), blocked)
                self.check(g)

    def test_source_silence_is_explicit_current_gate_and_ignore_profile_remains(self):
        for silence in ('ignore', 'requires_unsilenced'):
            self.spell('bind_' + silence, lambda c, s=silence: [self.bound(c, AttackSourcePolicy('live', 'preserve', s))], True)
        for silence, blocked in (('ignore', True), ('requires_unsilenced', False)):
            with self.subTest(silence=silence):
                g = self.game(hand=('bind_' + silence, 'silence', 'transform'))
                source, target = self.unit(g).id, self.unit(g, 1).id
                self.cast(g, 'bind_' + silence, target)
                self.cast(g, 'silence', source)
                self.assertEqual(not bool(self.attacks(g, target)), blocked)
                self.cast(g, 'transform', source)
                self.assertFalse(self.attacks(g, target))
                self.check(g)

    def test_dormancy_is_same_residence_and_live_vs_active_policy_differs(self):
        for presence in ('board_present', 'live', 'active'):
            self.spell('bind_' + presence, lambda c, p=presence: [self.bound(c, AttackSourcePolicy(p, 'preserve', 'ignore'))], True)
        for presence, blocked in (('board_present', True), ('live', True), ('active', False)):
            with self.subTest(presence=presence):
                g = self.game(hand=('bind_' + presence, 'dormant', 'awaken'))
                source, target = self.unit(g).id, self.unit(g, 1).id
                old_presence = g.state.entities[source].board_presence_id
                self.cast(g, 'bind_' + presence, target)
                self.cast(g, 'dormant', source)
                self.assertEqual(g.state.entities[source].board_presence_id, old_presence)
                self.assertEqual(not bool(self.attacks(g, target)), blocked)
                self.cast(g, 'awaken')
                self.assertEqual(g.state.entities[source].board_presence_id, old_presence)
                self.assertFalse(self.attacks(g, target))
                self.check(g)

    def test_target_current_copy_keeps_original_external_relation_and_new_attachment_id(self):
        g = self.game(hand=('bind', 'copy', 'basecopy', 'kill'))
        source, target = self.unit(g).id, self.unit(g, 1).id
        self.cast(g, 'bind', target)
        original = next(a for a in g.state.entities[target].abilities if a.kind == 'attack_policy')
        self.cast(g, 'copy', target)
        current = self.unit(g, 2)
        copied = next(a for a in current.abilities if a.kind == 'attack_policy')
        self.assertEqual(copied.attack_source_binding, original.attack_source_binding)
        self.assertNotEqual(copied.id, original.id)
        self.assertNotEqual(current.board_presence_id, g.state.entities[target].board_presence_id)
        self.assertFalse(self.attacks(g, current.id))
        self.cast(g, 'basecopy', target)
        base = self.unit(g, 3)
        self.assertFalse(any(a.kind == 'attack_policy' for a in base.abilities))
        self.cast(g, 'kill', source)
        self.assertTrue(self.attacks(g, current.id))
        self.check(g)

    def test_target_silence_transform_and_return_remove_relation_by_shared_lifecycle(self):
        for operation in ('silence', 'transform', 'bounce'):
            with self.subTest(operation=operation):
                g = self.game(hand=('bind', operation))
                target = self.unit(g, 1).id
                self.cast(g, 'bind', target)
                self.cast(g, operation, target)
                self.assertFalse(any(a.attack_source_binding for a in g.state.entities[target].abilities))
                self.check(g)

    def test_target_control_change_keeps_external_original_binding(self):
        self.spell('bind_enemy', lambda c: [self.bound(c)], True)
        g = self.game(board=('source',), hand=('bind_enemy', 'steal'), enemy=('plain',))
        target = self.unit(g, player=2).id
        self.cast(g, 'bind_enemy', target)
        original = self.binding(g, target)
        self.cast(g, 'steal', target)
        self.assertEqual(self.binding(g, target), original)
        self.assertFalse(self.attacks(g, target))
        self.check(g)

    def test_source_shuffle_clears_presence_and_hidden_resummon_gets_new_segment(self):
        self.spell('retrieve', lambda c: [SummonStoredCard(CardReference.capture(next(
            e for e in c.state.entities.values() if e.card_id == 'source' and e.zone == Zone.DECK)), c.player_id)])
        g = self.game(hand=('bind', 'shuffle', 'retrieve'))
        source, target = self.unit(g).id, self.unit(g, 1).id
        self.cast(g, 'bind', target)
        old = self.binding(g, target)
        self.cast(g, 'shuffle', source)
        self.assertIsNone(g.state.entities[source].board_presence_id)
        self.assertTrue(self.attacks(g, target))
        self.cast(g, 'retrieve')
        self.assertNotEqual(g.state.entities[source].board_presence_id, old.reference.presence_id)
        self.assertTrue(self.attacks(g, target))
        self.check(g)

    def test_body_battlecry_captures_original_source_before_return_and_pending_grant(self):
        self.r.register_behavior('bind_body', lambda c: [RequestChoice(c.player_id, (
            ChoiceOption('apply', 'Apply', effects=(self.bound(c, source_id=c.source_id),)),), source_id=c.source_id)])
        self.r.register_card(CardDefinition('body', 'body', CardType.MINION, attack=1, health=20,
            battlecry='bind_body', requires_target=True, keywords=(Keyword.CHARGE,)))
        g = self.game(board=('plain',), hand=('body',))
        target = self.unit(g).id
        self.cast(g, 'body', target)
        source = self.unit(g, 1).id
        choice = g.state.pending_choice
        self.assertIsNotNone(choice)
        for player in (1, 2):
            observed = json.dumps(g.observe(player))
            for private_field in ('presence_id', 'attack_source_binding', 'captured_zone_epoch'):
                self.assertNotIn(private_field, observed)
        self.check(g)
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r)
        clone = g.clone()
        action = SelectChoice(1, choice.id, ('apply',))
        for instance in (g, restored, clone): instance.apply(action)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.snapshot(), clone.snapshot())
        self.assertEqual(self.binding(g, target).reference.entity_id, source)
        self.assertFalse(self.attacks(g, target))
        self.check(g)

    def test_accepted_reference_survives_choice_roundtrip_but_leaving_before_grant_stales(self):
        def choose(c):
            grant = self.bound(c)
            return [RequestChoice(c.player_id, (ChoiceOption('apply', 'Apply', effects=(
                ReturnToHand(grant.source_id), grant)),), source_id=c.source_id)]
        self.spell('choose_stale', choose, True)
        g = self.game(hand=('choose_stale',))
        target = self.unit(g, 1).id
        self.cast(g, 'choose_stale', target)
        self.check(g)
        restored = Game.from_snapshot(g.snapshot(), self.r)
        action = SelectChoice(1, g.state.pending_choice.id, ('apply',))
        result = g.apply(action); restored.apply(action)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertFalse(any(a.attack_source_binding for a in g.state.entities[target].abilities))
        self.assertTrue(any(e.kind == 'effect_skipped' for e in result.events))
        self.check(g)

    def test_captured_binding_is_not_recaptured_after_same_entity_bounce_trigger_resummon(self):
        self.r.register_behavior('resummon_returned', lambda c: [SummonStoredCard(
            CardReference.capture(c.state.entities[c.event.target_id]), c.player_id)])
        self.r.register_card(CardDefinition('watcher', 'watcher', CardType.MINION, attack=1, health=20,
            triggers=(TriggerSpec('card_returned', 'resummon_returned'),)))
        self.spell('bounce_then_grant', lambda c: [ReturnToHand(self.source(c)), self.bound(c)], True)
        g = self.game(board=('source', 'plain', 'watcher'), hand=('bounce_then_grant',))
        source, target = self.unit(g).id, self.unit(g, 1).id
        old_presence = g.state.entities[source].board_presence_id
        result = self.cast(g, 'bounce_then_grant', target)
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        self.assertNotEqual(g.state.entities[source].board_presence_id, old_presence)
        self.assertFalse(any(a.attack_source_binding for a in g.state.entities[target].abilities))
        self.assertTrue(self.attacks(g, target))
        self.assertTrue(any(e.kind == 'effect_skipped' for e in result.events))
        self.check(g)

    def test_freeze_uses_source_policy_current_opportunity_without_retroactive_deadline_change(self):
        g = self.game(hand=('bind', 'freeze', 'kill'))
        source, target = self.unit(g).id, self.unit(g, 1).id
        self.cast(g, 'bind', target)
        self.cast(g, 'freeze', target)
        self.assertEqual(g.state.entities[target].frozen_until_owner_turn, 2)
        self.cast(g, 'kill', source)
        self.assertEqual(g.state.entities[target].frozen_until_owner_turn, 2)
        self.check(g)

    def test_current_frozen_target_copy_retains_stale_external_binding_and_recomputes_opportunity(self):
        g = self.game(hand=('bind', 'freeze', 'kill', 'copy'))
        source, target = self.unit(g).id, self.unit(g, 1).id
        self.cast(g, 'bind', target)
        self.cast(g, 'freeze', target)
        binding = self.binding(g, target)
        self.cast(g, 'kill', source)
        self.cast(g, 'copy', target)
        clone = self.unit(g, -1)
        self.assertEqual(self.binding(g, clone.id), binding)
        self.assertEqual(g.state.entities[target].frozen_until_owner_turn, 2)
        self.assertEqual(clone.frozen_until_owner_turn, 1)
        self.check(g)

    def test_bound_weapon_infinite_policy_projects_live_to_hero_and_preserves_used_count(self):
        self.r.register_card(CardDefinition('weapon', 'weapon', CardType.WEAPON, attack=1, durability=8))
        self.spell('equip_bound', lambda c: [EquipWeapon(c.player_id, 'weapon')])
        def bind_weapon(c):
            source = self.source(c)
            binding = AttackSourceBinding.capture(c.state, source, LIVE)
            return [GrantAttackPolicy(c.state.players[c.player_id].weapon_id,
                AttackPolicySpec('attacks_per_turn'), source_id=source, source_binding=binding)]
        self.spell('bind_weapon', bind_weapon)
        g = self.game(hand=('equip_bound', 'bind_weapon', 'kill'))
        source = self.unit(g).id
        self.cast(g, 'equip_bound'); self.cast(g, 'bind_weapon')
        hero = g.state.players[1].hero_id
        self.assertIsNone(attack_limit(g.state, g.state.entities[hero], self.r))
        for _ in range(2): g.apply(Attack(1, hero, g.state.players[2].hero_id))
        self.cast(g, 'kill', source)
        self.assertEqual(attack_limit(g.state, g.state.entities[hero], self.r), 1)
        self.assertEqual(g.state.entities[hero].attacks_this_turn, 2)
        self.assertFalse(self.attacks(g, hero))
        self.check(g)

    def test_present_live_active_have_explicit_dying_and_inactive_pure_boundaries(self):
        g = self.game()
        source = self.unit(g).id
        bindings = {p: AttackSourceBinding.capture(g.state, source, AttackSourcePolicy(p, 'preserve', 'ignore'))
                    for p in ('board_present', 'live', 'active')}
        state = deepcopy(g.state)
        state.entities[source].doomed = True
        self.assertTrue(attack_source_enabled(state, bindings['board_present']))
        self.assertFalse(attack_source_enabled(state, bindings['live']))
        self.assertFalse(attack_source_enabled(state, bindings['active']))
        state.entities[source].doomed = False
        state.entities[source].damage = state.entities[source].max_health
        self.assertTrue(attack_source_enabled(state, bindings['board_present']))
        self.assertFalse(attack_source_enabled(state, bindings['live']))
        self.assertEqual(g.snapshot(), self.game().snapshot())

    def test_starship_building_and_launch_keep_physical_segment_without_new_residence(self):
        self.r.register_card(CardDefinition('ship', 'ship', CardType.MINION, cost=5, starship_for=(CardClass.NEUTRAL,)))
        self.r.register_card(CardDefinition('piece', 'piece', CardType.MINION, attack=3, health=4,
                                            keywords=(Keyword.STARSHIP_PIECE,)))
        self.spell('bind_ship', lambda c: [self.bound(c, source_id=construction(c.state, c.player_id).id)], True)
        g = self.game(board=('plain', 'piece'), hand=('kill', 'bind_ship'))
        target = self.unit(g).id
        self.cast(g, 'kill', self.unit(g, 1).id)
        ship = construction(g.state, 1)
        old_presence = ship.board_presence_id
        self.cast(g, 'bind_ship', target)
        self.assertFalse(self.attacks(g, target))
        g.apply(LaunchStarship(1, ship.id))
        self.assertEqual(g.state.entities[ship.id].board_presence_id, old_presence)
        self.assertFalse(self.attacks(g, target))
        self.check(g)

    def test_entry_allocation_reuses_existing_order_and_stored_card_recruits_once(self):
        self.spell('stored', lambda c: [SummonStoredCard(CardReference.capture(c.state.entities[
            c.state.players[c.player_id].deck[0]]), c.player_id)])
        g = self.game(hand=('summon', 'stored'))
        for entity in g.state.entities.values():
            if entity.zone == Zone.BOARD and entity.kind == CardType.MINION:
                self.assertEqual(entity.board_presence_id, entity.entered_order)
            else:
                self.assertIsNone(entity.board_presence_id)
        for spell in ('summon', 'stored'):
            before_order = g.state.next_order
            self.cast(g, spell)
            added = self.unit(g, -1)
            self.assertEqual(added.board_presence_id, before_order)
            self.assertEqual(g.state.next_order, before_order + 1)
        self.check(g)

    def test_resurrection_new_physical_entity_does_not_reactivate_original_binding(self):
        self.spell('resurrect', lambda c: [ResurrectMinion(c.player_id, c.state.death_history[0].id)])
        g = self.game(hand=('bind', 'kill', 'resurrect'))
        source, target = self.unit(g).id, self.unit(g, 1).id
        self.cast(g, 'bind', target)
        self.cast(g, 'kill', source)
        self.cast(g, 'resurrect')
        revived = self.unit(g, -1)
        self.assertNotEqual(revived.id, source)
        self.assertIsNotNone(revived.board_presence_id)
        self.assertTrue(self.attacks(g, target))
        self.check(g)

    def test_failure_rolls_back_presence_orders_binding_rng_and_player_information(self):
        self.spell('fail', lambda c: [self.bound(c), Summon(c.player_id, 'source'),
            ShuffleIntoDeck(self.source(c)), Unhandled()], True)
        g = self.game(hand=('fail',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'fail', self.unit(g, 1).id)
        self.assertEqual(g.snapshot(), before)

    def test_failed_choice_restores_original_capture_and_all_residence_state(self):
        self.spell('bad_choice', lambda c: [RequestChoice(c.player_id, (
            ChoiceOption('fail', 'Fail', effects=(self.bound(c), ReturnToHand(self.source(c)),
                EquipWeapon(c.player_id, 'plain'))),), source_id=c.source_id)], True)
        g = self.game(hand=('bad_choice',))
        self.cast(g, 'bad_choice', self.unit(g, 1).id)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            g.apply(SelectChoice(1, g.state.pending_choice.id, ('fail',)))
        self.assertEqual(g.snapshot(), before)
        self.check(g)

    def test_unknown_sources_bad_types_and_mismatched_provenance_are_explicit_errors(self):
        self.spell('missing', lambda c: [GrantAttackPolicy(c.target_id, AttackPolicySpec('cannot_attack'),
            source_id=99999, source_binding=AttackSourceBinding(BoardPresenceReference(99999, 1), LIVE))], True)
        g = self.game()
        source, target = self.unit(g).id, self.unit(g, 1).id
        binding = AttackSourceBinding.capture(g.state, source, LIVE)
        for call in (lambda: BoardPresenceReference.capture(g.state, 99999),
                     lambda: BoardPresenceReference.capture(g.state, g.state.players[1].hero_id),
                     lambda: BoardPresenceReference(True, 1),
                     lambda: AttackSourcePolicy('unknown', 'preserve', 'ignore'),
                     lambda: AttackSourcePolicy('live', 'unknown', 'ignore'),
                     lambda: AttackSourcePolicy('live', 'preserve', 'unknown'),
                     lambda: AttackSourceBinding(binding.reference, LIVE, 0),
                     lambda: GrantAttackPolicy(target, AttackPolicySpec('cannot_attack'), source_binding=binding)):
            with self.assertRaises(ValueError): call()
        h = self.game(hand=('missing',)); before = h.snapshot()
        with self.assertRaises(ResolutionError): self.cast(h, 'missing', self.unit(h, 1).id)
        self.assertEqual(h.snapshot(), before)

    def test_snapshot_rejects_missing_duplicate_future_and_nonboard_residence(self):
        g = self.game()
        source, target = self.unit(g).id, self.unit(g, 1).id
        for entity_id, value in ((source, None), (target, g.state.entities[source].board_presence_id),
                                 (source, g.state.next_order), (g.state.players[1].hero_id, 1), (source, True)):
            with self.subTest(entity_id=entity_id, value=value):
                snap = deepcopy(g.snapshot())
                snap['state']['entities'][str(entity_id)]['board_presence_id'] = value
                snap['state_hash'] = canonical_hash({k: v for k, v in snap.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                with self.assertRaises(SnapshotError): Game.from_snapshot(snap, self.r)

    def test_internal_binding_fields_and_original_hidden_identity_not_in_player_dto(self):
        g = self.game(hand=('bind', 'shuffle'))
        source, target = self.unit(g).id, self.unit(g, 1).id
        self.cast(g, 'bind', target)
        self.cast(g, 'shuffle', source)
        for player in (1, 2):
            encoded = json.dumps(g.observe(player), ensure_ascii=False)
            for internal in ('board_presence_id', 'presence_id', 'attack_source_binding', 'captured_zone_epoch'):
                self.assertNotIn(internal, encoded)
        self.assertTrue(self.attacks(g, target))
        self.check(g)


if __name__ == '__main__':
    unittest.main()
