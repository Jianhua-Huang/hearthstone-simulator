"""Six new printed-permit / signed-Buff / physical-source combinations.

Synthetic declarations exercise isolated public contracts, not real-card or CN coverage.
"""
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, AttackPolicyCondition, AttackPolicySpec, AttackSourceBinding,
    AttackSourcePolicy, AuraSpec, CardDefinition, CardType, EndTurn, Game, GrantAttackPolicy,
    GrantPrintedAttackPermit, Keyword, PlayCard, PlayerSetup, PrintedAttackPolicyDeclaration,
    Registry, ResolutionError, Scenario, SelectChoice, Zone, capture_printed_attack_permit)
from hs_sim.engine.attack_policies import current_policies
from hs_sim.engine.board_presence import attack_source_enabled
from hs_sim.engine.effects import (Buff, ChoiceOption, CopyMinion, Damage, EquipWeapon, GainArmor,
    InvokeBehavior, RandomDamage, RemoveEnchantment, RequestChoice)
from hs_sim.engine.replay import build_replay, replay


BAN = AttackPolicySpec('cannot_attack')
LIVE = AttackSourcePolicy('active', 'preserve', 'ignore')


def registry():
    r = Registry('isolated-v129-six-cross-mechanism-combinations')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=100))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=6))
    r.register_card(CardDefinition('actor', 'Actor', CardType.MINION, attack=2, health=12,
        keywords=(Keyword.CHARGE,), attack_policies=(BAN,)))
    r.register_card(CardDefinition('aura', 'Aura', CardType.MINION, attack=1, health=6,
        auras=(AuraSpec(0, health=3),)))
    r.register_behavior('deathwait', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('record', 'Record', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)])
    r.register_card(CardDefinition('fragile', 'Fragile', CardType.MINION, attack=2, health=2,
        keywords=(Keyword.CHARGE,), attack_policies=(BAN,), deathrattle='deathwait'))

    def request(c):
        return capture_printed_attack_permit(c.state, r, c.target_id,
            PrintedAttackPolicyDeclaration(c.state.entities[c.target_id].card_id, 0))

    def permit(c):
        req = request(c)
        return [GrantPrintedAttackPermit(req)] if req else []

    def binding(c):
        source = c.state.players[c.player_id].board[1]
        return GrantAttackPolicy(c.target_id, BAN, source_id=source,
            source_binding=AttackSourceBinding.capture(c.state, source, LIVE))

    def lethal_capture(c):
        req = request(c)
        return [Buff(c.target_id, health=-20, source_id=c.source_id), GrantPrintedAttackPermit(req)]

    def kill_bound_source(c):
        grant = binding(c)
        return [Buff(grant.source_id, health=-7, source_id=c.source_id), grant]

    def wait(c):
        req = request(c)
        source = c.state.players[1].board[1]
        copies = (CopyMinion(c.target_id, 1),
                  InvokeBehavior('copy_last', player_id=1, source_id=c.source_id))
        good = (GrantPrintedAttackPermit(req), Buff(c.target_id, health=-3, source_id=c.source_id)) + copies
        bad = (GrantPrintedAttackPermit(req), Buff(c.target_id, health=-20, source_id=c.source_id),
               Buff(source, health=-7, source_id=c.source_id),
               RandomDamage((c.state.players[2].hero_id, c.state.players[2].board[0]), 1),
               EquipWeapon(1, 'plain'))
        return [Damage(c.target_id, 3, c.source_id), Buff(c.target_id, health=-2, source_id=c.source_id),
            RequestChoice(1, (ChoiceOption('good', 'Good', good), ChoiceOption('bad', 'Bad', bad)),
                          source_id=c.source_id)]

    r.register_behavior('copy_last', lambda c: [CopyMinion(c.state.players[c.player_id].board[-1], c.player_id)])
    bodies = {
        'permit': permit,
        'hurt': lambda c: [Damage(c.target_id, 3, c.source_id)],
        'neg': lambda c: [Buff(c.target_id, health=-5, source_id=c.source_id)],
        'zero': lambda c: [Buff(c.target_id, attack=-2, source_id=c.source_id)],
        'remove': lambda c: [RemoveEnchantment(c.target_id, c.state.entities[c.target_id].enchantments[-1].id)],
        'health_gate': lambda c: [GrantAttackPolicy(c.target_id,
            AttackPolicySpec('cannot_attack', conditions=(AttackPolicyCondition('health', 'gt', 5),)),
            source_id=c.source_id)],
        'bind': lambda c: [binding(c)],
        'lethal_capture': lethal_capture,
        'kill_bound_source': kill_bound_source,
        'wait': wait,
        'aura_driver': lambda c: [Buff(c.target_id, health=-4, source_id=c.source_id)] + permit(c),
        'aura_kill': lambda c: [Buff(c.state.players[1].board[0], health=-7, source_id=c.source_id)],
    }
    for name, fn in bodies.items():
        r.register_behavior(name, fn)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, requires_target=True))
    return r


class CrossMechanismTests(unittest.TestCase):
    def save_input(self, g, label):
        folder = os.environ.get('HS_V129_INPUTS')
        if folder:
            path = Path(folder)/self._testMethodName
            path.mkdir(parents=True, exist_ok=True)
            index = len(list(path.glob('*.json')))
            (path/(str(index).zfill(3)+'-'+label+'.json')).write_text(
                json.dumps(g.snapshot(), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    def game(self, hand, board=('actor', 'plain')):
        self.r = registry()
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', board=board, hand=hand, deck=('plain',)*5, mana=10, max_mana=10),
            PlayerSetup('hero', board=('plain',), deck=('plain',)*5, mana=10, max_mana=10),
        ), seed=129), self.r)

    def cast(self, g, name, target):
        self.save_input(g, 'before-cast-'+name)
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, eid, target))

    def permits(self, g, eid):
        return [a for a in g.state.entities[eid].abilities if a.kind == 'printed_attack_permit']

    def attacks(self, g, eid):
        return [a for a in g.legal_actions() if isinstance(a, Attack) and a.attacker_id == eid]

    def choose(self, g, option):
        self.save_input(g, 'before-choice-'+option)
        p = g.state.pending_choice
        return g.apply(SelectChoice(p.player_id, p.id, (option,)))

    def portable(self, g):
        self.save_input(g, 'snapshot-restore-clone-replay-input')
        snap = json.loads(json.dumps(g.snapshot()))
        independent = Game.from_snapshot(snap, registry())
        self.assertEqual(independent.snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap)
        return independent

    def private(self, g):
        public = json.dumps(g.observe(1)) + json.dumps(g.observe(2))
        public += json.dumps(g.for_player(1).legal_actions())
        for field in ('printed_attack_permit', 'permitted_ability_id', 'policy_index',
                      'expires_owner_turn_id', 'attack_source_binding', 'resolution_frame'):
            self.assertNotIn('"'+field+'"', public)

    def no_health_packets(self, result):
        self.assertFalse(any(e.kind in ('damage_dealt', 'healed', 'health_resolved', 'lifesteal')
                             for e in result.events))

    def test_negative_health_requeries_foreign_health_condition_without_widening_permission(self):
        g = self.game(('permit', 'health_gate', 'hurt', 'neg', 'zero', 'remove', 'remove'))
        actor = g.state.players[1].board[0]
        self.cast(g, 'permit', actor); original = self.permits(g, actor)[0]
        self.cast(g, 'health_gate', actor); self.cast(g, 'hurt', actor)
        self.assertFalse(self.attacks(g, actor))
        result = self.cast(g, 'neg', actor); self.no_health_packets(result)
        e = g.state.entities[actor]
        self.assertEqual((e.max_health, e.damage, e.health), (7, 3, 4))
        self.assertEqual(current_policies(g.state, e, self.r), ())
        self.assertEqual(self.permits(g, actor), [original]); self.assertTrue(self.attacks(g, actor))
        self.cast(g, 'zero', actor); self.assertEqual(g.state.entities[actor].attack, 0)
        self.assertFalse(self.attacks(g, actor)); self.assertEqual(self.permits(g, actor), [original])
        self.cast(g, 'remove', actor); self.assertTrue(self.attacks(g, actor))
        result = self.cast(g, 'remove', actor); self.no_health_packets(result)
        self.assertEqual((g.state.entities[actor].health, g.state.entities[actor].damage), (9, 3))
        self.assertFalse(self.attacks(g, actor)); self.assertEqual(self.permits(g, actor), [original])
        self.private(g); self.portable(g)

    def test_negative_death_makes_precaptured_native_request_stale_at_ordinary_checkpoint(self):
        g = self.game(('hurt', 'lethal_capture')); actor = g.state.players[1].board[0]
        self.cast(g, 'hurt', actor); result = self.cast(g, 'lethal_capture', actor)
        self.no_health_packets(result); d = g.state.death_history[-1]
        self.assertEqual((d.entity_id, d.max_health, d.damage, d.cause.kind), (actor, -8, 3, 'health_state'))
        self.assertEqual(d.cause.reason, 'Buff')
        self.assertFalse(any(a.kind == 'printed_attack_permit' for a in d.abilities))
        self.assertEqual(self.permits(g, actor), [])
        self.assertTrue(any(e.kind == 'effect_skipped' and dict(e.data).get('effect') == 'GrantPrintedAttackPermit'
                            for e in result.events))
        self.private(g); self.portable(g)

    def test_negative_source_death_disables_old_binding_and_stales_captured_grant_without_self_revoke(self):
        g = self.game(('permit', 'bind', 'kill_bound_source')); actor, source = g.state.players[1].board
        self.cast(g, 'permit', actor); original = self.permits(g, actor)[0]
        self.cast(g, 'bind', actor); self.assertFalse(self.attacks(g, actor))
        row = next(a for a in g.state.entities[actor].abilities if a.attack_source_binding is not None)
        result = self.cast(g, 'kill_bound_source', actor); self.no_health_packets(result)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertFalse(attack_source_enabled(g.state, row.attack_source_binding))
        self.assertIn(row, g.state.entities[actor].abilities)
        self.assertEqual(self.permits(g, actor), [original]); self.assertTrue(self.attacks(g, actor))
        self.assertEqual(sum(a.attack_source_binding is not None for a in g.state.entities[actor].abilities), 1)
        self.assertTrue(any(e.kind == 'effect_skipped' and dict(e.data).get('effect') == 'GrantAttackPolicy'
                            for e in result.events))
        self.portable(g)

    def test_waiting_precaptured_permit_signed_layers_and_two_local_copy_maps_restore_without_rearm(self):
        g = self.game(('wait',)); actor = g.state.players[1].board[0]
        self.cast(g, 'wait', actor); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((g.state.entities[actor].health, g.state.entities[actor].damage), (7, 3))
        self.private(g); restored = self.portable(g); clone = g.clone()
        for branch in (g, restored, clone):
            self.choose(branch, 'good')
            ids = (actor, *branch.state.players[1].board[-2:]); row_ids = []; enchant_ids = []
            for eid in ids:
                e = branch.state.entities[eid]
                self.assertEqual((e.max_health, e.damage, e.health), (7, 3, 4))
                self.assertEqual([a.health for a in e.enchantments], [-2, -3])
                row = next(a for a in e.abilities if a.kind == 'attack_policy' and a.origin == 'printed')
                permit = self.permits(branch, eid)[0].printed_attack_permit
                self.assertEqual((permit.permitted_ability_id, permit.expires_owner_turn_id), (row.id, 1))
                self.assertEqual(row.source_id, actor); self.assertTrue(self.attacks(branch, eid))
                row_ids.append(row.id); enchant_ids.extend(a.id for a in e.enchantments)
            self.assertEqual(len(set(row_ids)), 3); self.assertEqual(len(set(enchant_ids)), 6)
            self.private(branch); self.portable(branch)
            branch.apply(EndTurn(1))
            for eid in ids:
                self.assertEqual(self.permits(branch, eid), [])
                self.assertEqual(current_policies(branch.state, branch.state.entities[eid], self.r), (BAN,))
                self.assertEqual([a.health for a in branch.state.entities[eid].enchantments], [-2, -3])
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.snapshot(), clone.snapshot())

    def test_selected_failure_rolls_back_permission_signed_deaths_rng_original_clock_and_wait(self):
        g = self.game(('wait',)); actor, source = g.state.players[1].board
        self.cast(g, 'wait', actor); restored = self.portable(g); before = g.snapshot()
        interval = g.state.owner_turn_history
        for branch in (g, restored):
            history = branch.history
            with self.assertRaises(ResolutionError) as failed: self.choose(branch, 'bad')
            self.assertIn('weapon', str(failed.exception).lower())
            self.assertEqual(branch.snapshot(), before); self.assertEqual(branch.history, history)
            self.assertEqual(branch.state.owner_turn_history, interval)
            self.assertEqual(self.permits(branch, actor), []); self.assertFalse(branch.state.death_history)
            self.assertEqual(branch.state.entities[source].zone, Zone.BOARD)
            self.choose(branch, 'good'); self.assertEqual(len(self.permits(branch, actor)), 1)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_aura_source_negative_death_freezes_permitted_negative_carrier_in_second_batch_wait(self):
        g = self.game(('aura_driver', 'aura_kill'), board=('aura', 'fragile'))
        source, actor = g.state.players[1].board
        self.cast(g, 'aura_driver', actor); original = self.permits(g, actor)[0]
        self.assertEqual(g.state.entities[actor].health, 1); self.assertTrue(self.attacks(g, actor))
        result = self.cast(g, 'aura_kill', actor); self.no_health_packets(result)
        first, second = g.state.death_history
        self.assertEqual((first.entity_id, second.entity_id), (source, actor)); self.assertNotEqual(first.batch, second.batch)
        self.assertEqual((first.max_health, second.max_health), (-1, -2))
        self.assertIn(original, second.abilities); self.assertEqual(second.cause.kind, 'health_state')
        self.assertIsNone(second.cause.source_id); self.assertIsNotNone(g.state.pending_choice)
        self.private(g); restored = self.portable(g); clone = g.clone()
        for branch in (g, restored, clone):
            self.choose(branch, 'record'); self.assertEqual(branch.state.death_history[1], second)
            self.portable(branch)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.snapshot(), clone.snapshot())


if __name__ == '__main__':
    unittest.main()
