"""Eight new bounded cross-package cases; internal policies, not CN calibration."""
import json
import unittest

from hs_sim.engine import (ActivatedAbilitySpec, Attack, AttackPolicyCondition, AttackPolicySpec,
    AttackSourceBinding, AttackSourcePolicy, CardClass, CardDefinition, CardMetadata, CardType,
    CurrentTurnFactQuery, EndTurn, Game, GrantAttackPolicy, Keyword, PlayCard,
    ResolutionError, SelectChoice, TriggerSpec, UseMinionAbility, Zone, current_turn_fact_count)
from hs_sim.engine.attack_policies import attack_limit
from hs_sim.engine.board_presence import attack_source_enabled
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, ForceAttack,
    Freeze, GainArmor, RequestChoice)
from hs_sim.engine.interrupts import RedirectAttack
from tests import test_v119_attack_policies as attack_fixtures
from tests.test_v119_attack_policies import Unhandled

FRIEND = 'friendly_minions'
ACTIVE = AttackSourcePolicy('active', 'preserve', 'ignore')


def casts(phase='payload_accepted'):
    return CurrentTurnFactQuery('spell_cast', phase, 'owner_turn', ('hand',))


def hero_declared(window='owner_turn'):
    return CurrentTurnFactQuery('hero_attack', 'declared', window)


def conjunction(board_minimum=1, phase='payload_accepted'):
    return (AttackPolicyCondition('current_turn_fact_count', 'ge', 1, turn_fact=casts(phase)),
            AttackPolicyCondition('battlefield_minion_count', 'ge', board_minimum,
                                  board_scope='friendly', board_presence='active'))


class CombinedAttackTests(unittest.TestCase):
    def setUp(self):
        self.f = attack_fixtures.AttackPolicyTests(methodName='runTest')
        self.f.setUp()
        self.f.r.register_card(CardDefinition('actor', 'actor', CardType.MINION,
            attack=1, health=30, keywords=(Keyword.CHARGE,)))
        self.f.r.register_card(CardDefinition('actor_mega', 'actor_mega', CardType.MINION,
            attack=1, health=30, keywords=(Keyword.CHARGE, Keyword.MEGA_WINDFURY)))
        self.f.r.register_card(CardDefinition('fragile', 'fragile', CardType.MINION, attack=1, health=1))

    def bound(self, context, spec, source_position=1, actor_position=0):
        source = context.state.players[1].board[source_position]
        return GrantAttackPolicy(context.state.players[1].board[actor_position], spec,
            source_id=source, source_binding=AttackSourceBinding.capture(context.state, source, ACTIVE))

    def limit(self, game, entity_id):
        return attack_limit(game.state, game.state.entities[entity_id], self.f.r)

    def count(self, game, query=None):
        return current_turn_fact_count(game.state, 1, query or hero_declared())

    def binding(self, game, entity_id):
        return next(a.attack_source_binding for a in game.state.entities[entity_id].abilities
                    if a.kind == 'attack_policy' and a.attack_source_binding is not None)

    def private_fields_absent(self, game):
        public = json.dumps(game.observe(1)) + json.dumps(game.for_player(1).legal_actions())
        for field in ('turn_fact', 'owner_turn_id', 'recorded_event', 'attack_source_binding',
                      'board_presence_id', 'combat_relation'):
            self.assertNotIn('"' + field + '"', public)

    def restore_then_choose(self, game):
        self.f.check(game)
        restored = Game.from_snapshot(json.loads(json.dumps(game.snapshot())), self.f.r)
        choice = game.state.pending_choice
        action = SelectChoice(choice.player_id, choice.id, (choice.options[0].id,))
        game.apply(action)
        restored.apply(action)
        self.assertEqual(game.snapshot(), restored.snapshot())

    def test_nested_wait_serializes_binding_fact_and_friendly_force_while_frozen(self):
        f = self.f
        spec = AttackPolicySpec('attacks_per_turn', None, conjunction(3))
        def driver(c):
            actor, source = c.state.players[1].board[:2]
            return [Freeze(actor), RequestChoice(1, (ChoiceOption('go', 'Go',
                (self.bound(c, spec), ForceAttack(actor, source, combat_relation=FRIEND))),), source_id=c.source_id)]
        f.spell('driver', driver)
        g = f.game(board=('actor_mega', 'plain', 'plain'), hand=('driver',))
        actor, source = g.state.players[1].board[:2]
        resident = {i: g.state.entities[i].board_presence_id for i in (actor, source)}
        f.cast(g, 'driver')
        self.assertEqual([self.count(g, casts(p)) for p in ('payload_accepted', 'completed')], [1, 0])
        self.private_fields_absent(g)
        self.restore_then_choose(g)
        self.assertEqual([g.state.entities[i].damage for i in (actor, source)], [1, 1])
        self.assertEqual(g.state.entities[actor].attacks_this_turn, 0)
        self.assertEqual(g.state.entities[actor].frozen_until_owner_turn, 1)
        self.assertIsNone(self.limit(g, actor))
        self.assertEqual(self.count(g), 0)
        self.assertEqual({i: g.state.entities[i].board_presence_id for i in resident}, resident)
        self.private_fields_absent(g); f.check(g)

    def test_magnetic_reentry_cannot_revive_original_binding_or_reset_spent_quota(self):
        f = self.f
        meta = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',))
        f.r.register_card(CardDefinition('host', 'host', CardType.MINION, attack=1, health=30,
            keywords=(Keyword.CHARGE,), metadata=meta))
        f.r.register_card(CardDefinition('magnet', 'magnet', CardType.MINION, health=1,
            keywords=(Keyword.MAGNETIC, Keyword.MEGA_WINDFURY, Keyword.CHARGE),
            magnetic_tribes=('mech',), metadata=meta))
        f.spell('bind', lambda c: [self.bound(c, AttackPolicySpec('attacks_per_turn', None, conjunction()))])
        g = f.game(board=('host', 'magnet'), hand=('bind', 'bounce'))
        actor, source = g.state.players[1].board[:2]
        f.attack(g, source=actor); f.cast(g, 'bind')
        original = self.binding(g, actor)
        self.assertIsNone(self.limit(g, actor))
        f.cast(g, 'bounce', source)
        self.assertFalse(attack_source_enabled(g.state, original))
        g.apply(PlayCard(1, source, position=0))
        self.assertIsNone(g.state.entities[source].board_presence_id)
        self.assertFalse(attack_source_enabled(g.state, original))
        self.assertEqual(self.limit(g, actor), 4)
        self.assertEqual(g.state.entities[actor].attacks_this_turn, 1)
        for _ in range(3): f.attack(g, source=actor)
        self.assertFalse(f.attacks(g, actor))
        self.assertEqual(self.binding(g, actor), original)
        f.check(g)

    def test_friendly_death_disables_source_then_frozen_current_copy_recomputes_clock(self):
        f = self.f
        f.spell('bind', lambda c: [self.bound(c, AttackPolicySpec('attacks_per_turn', None, conjunction()))])
        f.spell('fight', lambda c: [ForceAttack(*c.state.players[1].board[:2], combat_relation=FRIEND)])
        g = f.game(board=('actor_mega', 'fragile'), hand=('bind', 'fight', 'freeze', 'copy'))
        actor, source = g.state.players[1].board[:2]
        f.cast(g, 'bind'); f.attack(g, source=actor); f.attack(g, source=actor)
        binding = self.binding(g, actor)
        f.cast(g, 'fight')
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertFalse(attack_source_enabled(g.state, binding))
        self.assertEqual((self.limit(g, actor), g.state.entities[actor].attacks_this_turn), (4, 2))
        f.cast(g, 'freeze', actor); f.cast(g, 'copy', actor)
        copy = g.state.players[1].board[-1]
        self.assertEqual([g.state.entities[i].frozen_until_owner_turn for i in (actor, copy)], [1, 1])
        self.assertEqual(g.state.entities[copy].attacks_this_turn, 0)
        self.assertNotEqual(g.state.entities[copy].board_presence_id, g.state.entities[actor].board_presence_id)
        self.assertEqual(self.binding(g, copy), binding)
        self.assertEqual(self.count(g), 0)
        f.check(g)

    def test_friendly_force_does_not_unlock_hero_declared_gate_or_spend_hero_weapon(self):
        f = self.f
        gate = AttackPolicyCondition('current_turn_fact_count', 'lt', 1, turn_fact=hero_declared())
        f.r.register_card(CardDefinition('gated', 'gated', CardType.MINION, attack=1, health=30,
            keywords=(Keyword.CHARGE,), attack_policies=(AttackPolicySpec('cannot_attack', conditions=(gate,)),)))
        f.spell('bind', lambda c: [self.bound(c, AttackPolicySpec('cannot_attack', conditions=conjunction(2, 'completed')))])
        f.spell('fight', lambda c: [ForceAttack(*c.state.players[1].board[:2], combat_relation=FRIEND)])
        g = f.game(board=('gated', 'plain'), hand=('bind', 'fight', 'kill'), weapon='weapon')
        actor, source = g.state.players[1].board[:2]
        weapon = g.state.players[1].weapon_id
        f.cast(g, 'bind'); f.cast(g, 'fight')
        self.assertFalse(f.attacks(g, actor))
        self.assertEqual(self.count(g), 0)
        self.assertEqual(g.state.entities[weapon].durability, 8)
        self.assertEqual(g.state.entities[actor].attacks_this_turn, 0)
        f.cast(g, 'kill', source)
        self.assertFalse(f.attacks(g, actor))
        g.apply(Attack(1, f.hero(g, 1), f.hero(g)))
        self.assertEqual(self.count(g), 1)
        self.assertTrue(f.attacks(g, actor))
        g.apply(EndTurn(1))
        self.assertEqual(self.count(g, hero_declared('current_turn')), 0)
        self.assertEqual(self.count(g), 0)
        f.check(g)

    def test_transfer_during_friendly_declaration_keeps_binding_but_rechecks_relation_and_count(self):
        f = self.f
        f.r.register_behavior('take', lambda c: [ChangeControl(c.event.target_id, 2)])
        f.r.register_card(CardDefinition('watch', 'watch', CardType.MINION, attack=1, health=30,
            keywords=(Keyword.CHARGE,), triggers=(TriggerSpec('attack_declared', 'take'),)))
        def driver(c):
            return [self.bound(c, AttackPolicySpec('attacks_per_turn', 3, conjunction(2))),
                    ForceAttack(*c.state.players[1].board[:2], combat_relation=FRIEND)]
        f.spell('driver', driver)
        g = f.game(board=('watch', 'plain'), hand=('driver', 'copy'))
        actor, source = g.state.players[1].board[:2]
        resident = g.state.entities[source].board_presence_id
        result = f.cast(g, 'driver')
        self.assertEqual(g.state.entities[source].controller, 2)
        self.assertEqual(g.state.entities[source].board_presence_id, resident)
        self.assertTrue(attack_source_enabled(g.state, self.binding(g, actor)))
        self.assertEqual([g.state.entities[i].damage for i in (actor, source)], [0, 0])
        self.assertEqual([dict(e.data)['reason'] for e in result.events if e.kind == 'attack_cancelled'],
                         ['combat_relation_changed'])
        self.assertEqual((self.limit(g, actor), g.state.entities[actor].attacks_this_turn), (1, 0))
        f.cast(g, 'copy', actor)
        copy = g.state.players[1].board[-1]
        self.assertEqual(self.limit(g, actor), 3)
        self.assertEqual(self.limit(g, copy), 3)
        self.assertEqual(self.binding(g, copy), self.binding(g, actor))
        self.assertEqual(self.count(g), 0)
        f.check(g)

    def test_friendly_redirect_wait_restores_all_new_fields_and_source_copy_is_distinct(self):
        f = self.f
        spec = AttackPolicySpec('attacks_per_turn', 3, conjunction(3))
        def paused(c):
            actor, source, target = c.state.players[1].board[:3]
            return [RequestChoice(1, (ChoiceOption('go', 'Go',
                (CopyMinion(source, 1), RedirectAttack(dict(c.event.data)['window_id'], target),
                 self.bound(c, spec))),), source_id=c.source_id)]
        f.r.register_behavior('paused', paused)
        f.r.register_card(CardDefinition('watch', 'watch', CardType.MINION, attack=1, health=30,
            triggers=(TriggerSpec('attack_declared', 'paused'),)))
        f.spell('driver', lambda c: [self.bound(c, spec),
            ForceAttack(*c.state.players[1].board[:2], combat_relation=FRIEND)])
        g = f.game(board=('actor', 'plain', 'watch'), hand=('driver',))
        actor, source, target = g.state.players[1].board
        f.cast(g, 'driver')
        self.assertEqual(g.state.action_windows[0].combat_relation, FRIEND)
        self.private_fields_absent(g)
        self.restore_then_choose(g)
        copy = g.state.players[1].board[-1]
        self.assertEqual([g.state.entities[i].damage for i in (actor, source, target)], [1, 0, 1])
        self.assertNotEqual(g.state.entities[source].board_presence_id, g.state.entities[copy].board_presence_id)
        self.assertEqual(self.binding(g, actor).reference.entity_id, source)
        self.assertEqual((self.limit(g, actor), g.state.entities[actor].attacks_this_turn), (3, 0))
        self.assertEqual(self.count(g), 0)
        self.private_fields_absent(g); f.check(g)

    def test_titan_freeze_uses_abilities_even_with_bound_ban_and_friendly_force_spends_none(self):
        f = self.f
        f.r.register_behavior('armor_one', lambda c: [GainArmor(c.player_id, 1)])
        f.r.register_card(CardDefinition('titan_mega', 'titan_mega', CardType.MINION, attack=1, health=30,
            keywords=(Keyword.TITAN, Keyword.MEGA_WINDFURY),
            activated_abilities=tuple(ActivatedAbilitySpec(str(i), 'armor_one') for i in range(3))))
        f.spell('bind', lambda c: [self.bound(c, AttackPolicySpec('cannot_attack', conditions=conjunction(2, 'completed')))])
        f.spell('fight', lambda c: [ForceAttack(*c.state.players[1].board[:2], combat_relation=FRIEND)])
        g = f.game(board=('titan_mega', 'fragile'), hand=('bind', 'freeze', 'fight'))
        actor, source = g.state.players[1].board[:2]
        f.cast(g, 'bind'); f.cast(g, 'freeze', actor)
        self.assertEqual(g.state.entities[actor].frozen_until_owner_turn, 1)
        f.cast(g, 'fight')
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertFalse(attack_source_enabled(g.state, self.binding(g, actor)))
        self.assertEqual(g.state.entities[actor].attacks_this_turn, 0)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertFalse(g.state.entities[actor].frozen)
        for i in range(3): g.apply(UseMinionAbility(1, actor, str(i)))
        self.assertEqual(g.state.entities[actor].attacks_this_turn, 3)
        f.attack(g, source=actor)
        self.assertEqual(g.state.entities[actor].attacks_this_turn, 4)
        self.assertFalse(f.attacks(g, actor))
        self.assertEqual(self.count(g), 0)
        self.assertEqual(self.count(g, casts('attempt')), 0)
        f.check(g)

    def test_failure_rolls_back_source_attachment_friendly_death_and_cast_fact_together(self):
        f = self.f
        f.spell('bad', lambda c: [self.bound(c, AttackPolicySpec('attacks_per_turn', 3, conjunction(2))),
            ForceAttack(*c.state.players[1].board[:2], combat_relation=FRIEND), Unhandled()])
        g = f.game(board=('actor', 'fragile'), hand=('bad',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError): f.cast(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.count(g, casts('attempt')), 0)
        self.assertEqual(self.count(g), 0)
        self.assertEqual(g.state.entities[f.unit(g, 1).id].zone, Zone.BOARD)
        self.assertFalse(any(a.attack_source_binding is not None for a in f.unit(g).abilities))
        f.check(g)
