"""Real public grants/lifecycle exercise the pure host target declaration seam."""
from dataclasses import replace
import unittest

from hs_sim.engine import (BodyReference, BodyTargetProfile, BodyTargetReference, CardDefinition, CardType,
    EndTurn, Game, GrantBattlecry, GrantCombo, Keyword, PlayCard, PlayerSetup, Registry, Scenario,
    TargetMode, TargetSpec, Zone, body_target_contract, body_target_declaration, body_target_declarations)
from hs_sim.engine.body_grants import ConsumeGrantedBody, RemoveGrantedBody
from hs_sim.engine.effects import ChangeControl, CopyMinion, GainArmor, ReturnToHand, Silence, Transform
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.registry import UnsupportedDefinitionError


PAID = BodyTargetProfile('paid', 'paid_hand', 'manual', 'pre_payment')
GENERATED = BodyTargetProfile('generated', 'generated_whole', 'random', 'generated_acceptance')


def registry(profiles=True):
    r = Registry('body-target-declarations-host-only')
    if profiles:
        for p in (PAID, GENERATED): r.register_body_target_profile(p)
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=100))
    r.register_behavior('bc', lambda c: [GainArmor(c.player_id, 1)])
    r.register_behavior('combo', lambda c: [GainArmor(c.player_id, 1)])
    r.register_card(CardDefinition('unit', 'Unit', CardType.MINION, cost=1, attack=1, health=10,
        battlecry='bc', combo='combo', manathirst=3, keywords=(Keyword.COMBO, Keyword.MANATHIRST)))
    r.register_card(CardDefinition('form', 'Form', CardType.MINION, attack=1, health=10))
    r.register_card(CardDefinition('high', 'High', CardType.MINION, health=10,
        battlecry='bc', manathirst=9, keywords=(Keyword.MANATHIRST,)))
    r.register_card(CardDefinition('low', 'Low', CardType.MINION, health=10,
        combo='combo', manathirst=5, keywords=(Keyword.COMBO, Keyword.MANATHIRST)))
    friendly = TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,), 'friendly')
    enemy = TargetSpec(TargetMode.OPTIONAL, (Zone.HERO, Zone.BOARD), (CardType.HERO, CardType.MINION), 'enemy')
    available = TargetSpec(TargetMode.IF_AVAILABLE, (Zone.HAND,), (CardType.MINION,), 'friendly')
    r.register_card(CardDefinition('friendly', 'Friendly', CardType.MINION, health=10, battlecry='bc', targeting=friendly,
        target_rule='any_entity', target_condition='manathirst', manathirst=5, keywords=(Keyword.MANATHIRST,)))
    r.register_card(CardDefinition('enemy', 'Enemy', CardType.MINION, health=10, combo='combo', targeting=enemy,
        target_rule='any_entity', target_condition='manathirst', manathirst=9, keywords=(Keyword.COMBO, Keyword.MANATHIRST)))
    r.register_card(CardDefinition('available', 'Available', CardType.MINION, health=10, battlecry='bc', targeting=available,
        target_rule='any_entity'))
    def never_run(c): raise AssertionError('Pure declarations must not run a target callback')
    for visibility in ('player', 'omniscient'):
        r.register_target_rule('custom.' + visibility, never_run, visibility=visibility)
        r.register_card(CardDefinition('custom.' + visibility, visibility, CardType.MINION, health=10,
            battlecry='bc', targeting=friendly, target_rule='custom.' + visibility))


    def setup(c):
        e = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == 'unit')
        return [GrantBattlecry(BodyReference.capture(e), 'high', c.source_id), GrantCombo(BodyReference.capture(e), 'low', c.source_id)]
    r.register_behavior('setup', setup)
    r.register_card(CardDefinition('setup', 'Setup', CardType.SPELL, cost=1, on_play='setup'))
    for name, callback in (
        ('silence', lambda c: [Silence(c.target_id)]), ('form', lambda c: [Transform(c.target_id, 'form')]),
        ('flip', lambda c: [ChangeControl(c.target_id, 2)]), ('copy', lambda c: [CopyMinion(c.target_id, c.player_id)]),
        ('bounce', lambda c: [ReturnToHand(c.target_id)])):
        behavior = 'mutate.' + name; r.register_behavior(behavior, callback)
        r.register_card(CardDefinition('spell.' + name, name, CardType.SPELL, on_play=behavior, requires_target=True))
    def mutation(c, effect):
        e = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == 'unit')
        a = next(a for a in e.abilities if a.kind == 'battlecry' and a.origin == 'granted')
        return [effect(BodyReference.capture(e), a.id, 'battlecry', c.source_id)]
    for name, effect in (('consume', ConsumeGrantedBody), ('remove', RemoveGrantedBody)):
        r.register_behavior(name, lambda c, effect=effect: mutation(c, effect))
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=0, on_play=name))
    return r


class BodyTargetDeclarationTests(unittest.TestCase):
    def game(self, board=False):
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('setup', 'unit', 'consume', 'remove', 'spell.silence', 'spell.form', 'spell.flip', 'spell.copy', 'spell.bounce'), mana=10, max_mana=10), PlayerSetup('hero')), active_player=1), registry())
        self.play(g, 'setup')
        if board: self.play(g, 'unit')
        return g

    def unit(self, g):
        return next(e for e in g.state.entities.values() if e.card_id == 'unit' and e.zone in (Zone.HAND, Zone.BOARD))

    def play(self, g, name, target=None):
        e = next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        g.apply(PlayCard(1, e.id, target))

    def declarations(self, g, profile='paid'):
        return body_target_declarations(g.state, g.registry, BodyReference.capture(self.unit(g)), profile)

    def test_registered_heterogeneous_domains_modes_thresholds_and_conditions_are_distinct(self):
        r = registry()
        friendly = body_target_contract(r, 'friendly', 'battlecry'); enemy = body_target_contract(r, 'enemy', 'combo')
        available = body_target_contract(r, 'available', 'battlecry')
        self.assertEqual((friendly.targeting.relation, enemy.targeting.relation), ('friendly', 'enemy'))
        self.assertEqual((friendly.targeting.mode, enemy.targeting.mode, available.targeting.mode), (TargetMode.REQUIRED, TargetMode.OPTIONAL, TargetMode.IF_AVAILABLE))
        self.assertEqual((friendly.manathirst_threshold, enemy.manathirst_threshold), (5, 9))
        self.assertEqual((friendly.activation_condition, enemy.activation_condition), (None, 'combo'))
        self.assertEqual((friendly.target_condition, enemy.target_condition), ('manathirst', 'manathirst'))
        self.assertEqual(friendly.target_visibility, 'builtin')
        for visibility in ('player', 'omniscient'):
            self.assertEqual(body_target_contract(r, 'custom.' + visibility, 'battlecry').target_visibility, visibility)

        with self.assertRaises(ValueError): body_target_contract(r, 'friendly', 'combo')
        with self.assertRaises(UnsupportedDefinitionError): body_target_contract(r, 'unknown', 'battlecry')

    def test_real_printed_and_public_granted_bodies_have_separate_exact_identities(self):
        g = self.game(); before = g.snapshot(); result = self.declarations(g)
        self.assertEqual([d.reference.family for d in result], ['battlecry', 'battlecry', 'combo', 'combo'])
        self.assertEqual([d.contract.declaration_card_id for d in result], ['unit', 'high', 'unit', 'low'])
        self.assertEqual([d.contract.manathirst_threshold for d in result], [3, 9, 3, 5])
        self.assertEqual([d.reference.origin for d in result], ['printed', 'granted', 'printed', 'granted'])
        self.assertEqual(len({d.reference.ability_id for d in result}), 4)
        self.assertEqual(g.snapshot(), before)
        for d in result: self.assertEqual(body_target_declaration(g.state, g.registry, d.reference, 'paid'), d)

    def test_profile_declarations_are_explicit_frozen_and_fingerprint_bound(self):
        r = registry(); old = r.fingerprint(); r.register_body_target_profile(replace(GENERATED, id='explicit', selection='explicit'))
        self.assertNotEqual(r.fingerprint(), old)
        with self.assertRaises(ValueError): r.register_body_target_profile(PAID)
        with self.assertRaises(UnsupportedDefinitionError): r.body_target_profile('missing')
        with self.assertRaises(TypeError): r.body_target_profiles['x'] = PAID
        r.freeze()
        with self.assertRaises(ValueError): r.register_body_target_profile(replace(PAID, id='later'))
        for delta in ({'origin': 'effect'}, {'selection': 'random'}, {'acceptance_window': 'payload'}, {'repeat_targets': 'redraw'}, {'late_bodies': 'inherit_root'}, {'retained_targets': 'redraw'}, {'stale_targets': 'retarget'}):
            with self.subTest(delta=delta), self.assertRaises(ValueError): replace(PAID, **delta)

    def test_granted_consume_and_remove_retire_only_that_exact_body_reference(self):
        for name in ('consume', 'remove'):
            with self.subTest(name=name):
                g = self.game(); old = self.declarations(g); chosen = old[1].reference
                self.play(g, name); current = self.declarations(g)
                self.assertEqual([d.reference.ability_id for d in current], [old[i].reference.ability_id for i in (0, 2, 3)])
                with self.assertRaises(ValueError): body_target_declaration(g.state, g.registry, chosen, 'paid')

    def test_silence_and_transform_invalidate_original_declarations(self):
        for name in ('spell.silence', 'spell.form'):
            with self.subTest(name=name):
                g = self.game(board=True); old = self.declarations(g); entity = self.unit(g)
                self.play(g, name, entity.id)
                for d in old:
                    with self.assertRaises(ValueError): body_target_declaration(g.state, g.registry, d.reference, 'paid')
                fresh = BodyReference.capture(g.state.entities[entity.id])
                self.assertEqual(body_target_declarations(g.state, g.registry, fresh, 'paid'), ())

    def test_control_and_zone_reentry_cannot_reuse_original_source_identity(self):
        for name in ('spell.flip', 'spell.bounce'):
            with self.subTest(name=name):
                g = self.game(board=True); old = self.declarations(g); entity = self.unit(g)
                self.play(g, name, entity.id)
                if name == 'spell.bounce': self.play(g, 'unit')
                for d in old:
                    with self.assertRaises(ValueError): body_target_declaration(g.state, g.registry, d.reference, 'paid')

    def test_current_copy_allocates_new_carrier_and_attachment_identities(self):
        g = self.game(board=True); original = self.unit(g); old = self.declarations(g)
        self.play(g, 'spell.copy', original.id)
        copy = next(g.state.entities[i] for i in g.state.players[1].board if i != original.id)
        current = body_target_declarations(g.state, g.registry, BodyReference.capture(copy), 'generated')
        self.assertEqual([d.contract for d in current], [d.contract for d in old])
        self.assertFalse(set(d.reference.ability_id for d in current) & set(d.reference.ability_id for d in old))
        for d in old:
            with self.assertRaises(ValueError): body_target_declaration(g.state, g.registry, replace(d.reference, carrier=BodyReference.capture(copy)), 'generated')

    def test_snapshot_clone_and_actual_action_replay_preserve_declaration_queries(self):
        g = self.game(board=True); expected = self.declarations(g, 'generated')
        restored = Game.from_snapshot(g.snapshot(), registry()); cloned = g.clone(); replayed = replay(build_replay(g), registry())
        for other in (restored, cloned, replayed): self.assertEqual(self.declarations(other, 'generated'), expected)
        # Profiles are part of the registry identity and cannot be silently omitted on restore.
        with self.assertRaises(ValueError): Game.from_snapshot(g.snapshot(), registry(False))

    def test_references_cannot_borrow_sibling_family_declaration_or_provenance(self):
        g = self.game(); original = self.declarations(g)[1].reference
        for delta in ({'family': 'combo'}, {'declaration_card_id': 'low'}, {'ability_id': self.declarations(g)[3].reference.ability_id}, {'origin': 'printed'}, {'grant_source_id': self.unit(g).id}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                body_target_declaration(g.state, g.registry, replace(original, **delta), 'paid')
        with self.assertRaises(ValueError): replace(original, ability_id=True)
        with self.assertRaises(ValueError): body_target_declarations(g.state, g.registry, original, 'paid')

    def test_host_declarations_do_not_become_player_capabilities_or_run_target_callbacks(self):
        g = self.game(); before = g.snapshot(); left = g.for_player(1).observe(); right = g.for_player(2).observe()
        paid = self.declarations(g, 'paid'); generated = self.declarations(g, 'generated')
        self.assertEqual([d.reference for d in paid], [d.reference for d in generated])
        self.assertTrue(all(d.profile.selection == 'manual' for d in paid))
        self.assertTrue(all(d.profile.selection == 'random' for d in generated))
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.for_player(1).observe(), left); self.assertEqual(g.for_player(2).observe(), right)
        self.assertFalse(any('body_target_profiles' in str(o) or 'pre_payment' in str(o) for o in (left, right)))


if __name__ == '__main__': unittest.main()
