"""Trusted source policies, real public grants and physical lifecycle checks."""
from dataclasses import replace
import unittest

from hs_sim.engine import (BodyReference, BodyTargetBinding, BodyTargetProfile, BodyTargetAuthority,
    AuthorizedPaidBodyTargetSubmission, BodyTargetSelection, PaidBodyTargetRequest, CardDefinition,
    CardType, EndTurn, Game, GrantBattlecry, IllegalAction, PlayCard, PlayerSetup, Scenario, Zone,
    authorize_paid_body_targets, body_target_authorities, body_target_authority,
    body_target_declarations, paid_body_target_plan, preflight_paid_body_targets,
    validate_authorized_paid_body_targets)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.registry import UnsupportedDefinitionError
from test_paid_body_target_preflight import registry as preflight_registry
from test_body_target_declarations import registry as lifecycle_registry


def registry(*, omit=(), origins=('printed', 'granted'), carrier_kinds=(CardType.MINION, CardType.WEAPON, CardType.HERO),
             carrier_ids=(), profile='paid', mode='normal', condition=None):
    r = preflight_registry(condition=condition, mode=mode)
    r.register_body_target_profile(BodyTargetProfile('paid2', 'paid_hand', 'manual', 'pre_payment'))
    for card_id in ('unit', 'low', 'high', 'weapon'):
        for family in ('battlecry', 'combo'):
            if getattr(r.card(card_id), family) is not None and (card_id, family) not in omit:
                r.register_body_target_binding(BodyTargetBinding(card_id, family, profile,
                    origins, carrier_kinds, carrier_ids))
    return r


def physical_registry():
    r = lifecycle_registry()
    for card_id in ('unit', 'high', 'low', 'custom.player', 'custom.omniscient'):
        for family in ('battlecry', 'combo'):
            if getattr(r.card(card_id), family) is not None:
                for profile in ('paid', 'generated'):
                    r.register_body_target_binding(BodyTargetBinding(card_id, family, profile))
    return r


class BodyTargetAuthorityTests(unittest.TestCase):
    def game(self, *, r=None, grant=True):
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('setup', 'unit', 'tempo', 'consume', 'remove', 'hold'),
            board=('friend', 'friend'), mana=6, max_mana=6, armor=10),
            PlayerSetup('hero', board=('enemy',), hand=('enemy',)))), r or registry())
        if grant:
            self.play(g, 'setup')
        return g

    def play(self, g, name, target=None):
        e = next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        g.apply(PlayCard(1, e.id, target))

    def unit(self, g):
        return next(e for e in g.state.entities.values() if e.card_id == 'unit' and e.zone in (Zone.HAND, Zone.BOARD))

    def request(self, g, profile='paid'):
        action = PlayCard(1, self.unit(g).id, g.state.players[1].board[0])
        plan = paid_body_target_plan(g, action, profile)
        return PaidBodyTargetRequest(action, profile, tuple(BodyTargetSelection(r.declaration.reference,
            r.target_choices[i % len(r.target_choices)] if r.target_choices else None)
            for i, r in enumerate(plan.requirements)))

    def physical_game(self, *, board=False):
        hand = ('setup', 'unit', 'consume', 'remove', 'spell.silence', 'spell.form', 'spell.flip', 'spell.copy', 'spell.bounce')
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, mana=10, max_mana=10), PlayerSetup('hero'))), physical_registry())
        self.play(g, 'setup')
        if board:
            self.play(g, 'unit')
        return g

    def test_real_six_body_authorization_is_complete_ordered_and_does_not_pay(self):
        g = self.game(); before = g.snapshot(); observations = [g.for_player(p).observe() for p in (1, 2)]
        a = authorize_paid_body_targets(g, self.request(g))
        self.assertEqual(len(a.authorities), 6)
        self.assertEqual([x.binding.declaration_card_id for x in a.authorities], ['unit', 'low', 'high'] * 2)
        self.assertEqual([x.declaration.reference.origin for x in a.authorities], ['printed', 'granted', 'granted'] * 2)
        self.assertEqual(len({x.target_id for x in a.submission.selected}), 2)
        self.assertEqual(validate_authorized_paid_body_targets(g, a), a)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual([g.for_player(p).observe() for p in (1, 2)], observations)

    def test_known_profile_and_valid_plan_cannot_authorize_an_unbound_card(self):
        g = self.game(r=registry(omit=(('unit', 'battlecry'),))); request = self.request(g); before = g.snapshot()
        self.assertEqual(len(preflight_paid_body_targets(g, request).selected), 6)
        with self.assertRaises(IllegalAction): authorize_paid_body_targets(g, request)
        self.assertEqual(g.snapshot(), before)

    def test_printed_carrier_policy_never_implicitly_authorizes_its_granted_bodies(self):
        g = self.game(r=registry(omit=(('high', 'combo'),))); before = g.snapshot()
        with self.assertRaises(IllegalAction): authorize_paid_body_targets(g, self.request(g))
        self.assertEqual(g.snapshot(), before)

    def test_disabled_combo_still_needs_its_exact_source_policy(self):
        g = self.game(r=registry(omit=(('unit', 'combo'),)), grant=False); request = self.request(g)
        plan = preflight_paid_body_targets(g, request)
        self.assertFalse(plan.plan.requirements[1].body_active)
        with self.assertRaises(IllegalAction): authorize_paid_body_targets(g, request)

    def test_registered_origins_cannot_be_used_by_other_physical_provenance(self):
        for origins, grant in ((('printed',), True), (('granted',), False)):
            g = self.game(r=registry(origins=origins), grant=grant); before = g.snapshot()
            with self.assertRaises(IllegalAction): authorize_paid_body_targets(g, self.request(g))
            self.assertEqual(g.snapshot(), before)

    def test_another_paid_profile_or_generated_binding_is_not_paid_permission(self):
        for r, profile in ((registry(), 'paid2'), (registry(profile='generated'), 'paid')):
            g = self.game(r=r); before = g.snapshot()
            with self.assertRaises(IllegalAction): authorize_paid_body_targets(g, self.request(g, profile))
            self.assertEqual(g.snapshot(), before)

    def test_actual_carrier_kind_and_card_restrictions_are_enforced(self):
        for kinds, ids in (((CardType.WEAPON,), ()), ((CardType.MINION, CardType.WEAPON, CardType.HERO), ('low',))):
            r = preflight_registry()
            for card_id in ('unit', 'low', 'high'):
                for family in ('battlecry', 'combo'):
                    r.register_body_target_binding(BodyTargetBinding(card_id, family, 'paid', carrier_kinds=kinds, carrier_card_ids=ids))
            g = self.game(r=r); before = g.snapshot()
            with self.assertRaises(IllegalAction): authorize_paid_body_targets(g, self.request(g))
            self.assertEqual(g.snapshot(), before)

    def test_binding_denial_happens_before_any_target_predicate(self):
        g = self.game(r=registry(omit=(('unit', 'battlecry'),), mode='never'), grant=False)
        request = PaidBodyTargetRequest(PlayCard(1, self.unit(g).id, g.state.players[1].board[0]), 'paid', ())
        before = g.snapshot()
        with self.assertRaises(IllegalAction): authorize_paid_body_targets(g, request)
        self.assertEqual(g.snapshot(), before)

    def test_typed_bindings_registry_references_duplicates_and_freezing_are_strict(self):
        r = preflight_registry()
        spec = BodyTargetBinding('unit', 'battlecry', 'paid')
        for delta in ({'family': 'deathrattle'}, {'origins': ()}, {'origins': ['printed']},
                      {'origins': ('printed', 'printed')}, {'carrier_kinds': (CardType.SPELL,)},
                      {'carrier_card_ids': ['unit']}, {'carrier_card_ids': ('unit', 'unit')}):
            with self.subTest(delta=delta), self.assertRaises(ValueError): replace(spec, **delta)
        for delta in ({'declaration_card_id': 'missing'}, {'profile_id': 'missing'},
                      {'declaration_card_id': 'hero'}, {'carrier_card_ids': ('tempo',)}):
            with self.subTest(delta=delta), self.assertRaises(ValueError): r.register_body_target_binding(replace(spec, **delta))
        r.register_body_target_binding(spec)
        with self.assertRaises(ValueError): r.register_body_target_binding(spec)
        with self.assertRaises(TypeError): r.body_target_bindings[('unit', 'battlecry', 'paid')] = spec
        r.freeze()
        with self.assertRaises(ValueError): r.register_body_target_binding(replace(spec, family='combo'))

    def test_ambiguous_profiles_with_same_origin_are_rejected_without_mutation(self):
        r = registry(); before = r.fingerprint()
        with self.assertRaises(ValueError): r.register_body_target_binding(BodyTargetBinding('unit', 'battlecry', 'paid2'))
        self.assertEqual(r.fingerprint(), before)
        r.register_body_target_binding(BodyTargetBinding('unit', 'battlecry', 'generated'))
        self.assertNotEqual(r.fingerprint(), before)

    def test_binding_fingerprint_is_order_independent_and_empty_table_preserves_parent(self):
        a, b = preflight_registry(), preflight_registry(); old = a.fingerprint()
        specs = [BodyTargetBinding('unit', f, 'paid') for f in ('battlecry', 'combo')]
        for spec in specs: a.register_body_target_binding(spec)
        for spec in reversed(specs): b.register_body_target_binding(spec)
        self.assertEqual(a.fingerprint(), b.fingerprint()); self.assertNotEqual(a.fingerprint(), old)
        c = preflight_registry(); self.assertEqual(c.fingerprint(), old)

    def test_host_made_broader_binding_receipt_is_recomputed_and_rejected(self):
        g = self.game(r=registry(origins=('printed', 'granted'), carrier_ids=('unit',))); a = authorize_paid_body_targets(g, self.request(g))
        forged = replace(a.authorities[0], binding=replace(a.authorities[0].binding, carrier_card_ids=()))
        receipt = replace(a, authorities=(forged, *a.authorities[1:])); before = g.snapshot()
        with self.assertRaises(IllegalAction): validate_authorized_paid_body_targets(g, receipt)
        with self.assertRaises(ValueError): replace(a, authorities=tuple(reversed(a.authorities)))
        self.assertEqual(g.snapshot(), before)

    def test_consume_remove_and_later_real_action_invalidate_the_original_authorization(self):
        for name in ('consume', 'remove', 'tempo'):
            g = self.game(); a = authorize_paid_body_targets(g, self.request(g)); self.play(g, name); before = g.snapshot()
            with self.assertRaises((ValueError, IllegalAction)): validate_authorized_paid_body_targets(g, a)
            fresh = authorize_paid_body_targets(g, self.request(g))
            self.assertEqual(len(fresh.authorities), 6 if name == 'tempo' else 5)
            self.assertEqual(g.snapshot(), before)

    def test_snapshot_clone_and_actual_action_replay_recompute_the_same_authorities(self):
        g = self.game(); a = authorize_paid_body_targets(g, self.request(g))
        for other in (Game.from_snapshot(g.snapshot(), registry()), g.clone(), replay(build_replay(g), registry())):
            self.assertEqual(validate_authorized_paid_body_targets(other, a), a)

    def test_current_copy_gets_new_physical_authority_and_cannot_borrow_original_reference(self):
        g = self.physical_game(board=True); entity = self.unit(g)
        old = body_target_authorities(g.state, g.registry, BodyReference.capture(entity), 'paid')
        self.play(g, 'spell.copy', entity.id)
        copied = next(g.state.entities[i] for i in g.state.players[1].board if i != entity.id)
        fresh = body_target_authorities(g.state, g.registry, BodyReference.capture(copied), 'paid')
        self.assertEqual([a.binding for a in old], [a.binding for a in fresh])
        self.assertTrue(set(a.declaration.reference.ability_id for a in old).isdisjoint(a.declaration.reference.ability_id for a in fresh))
        for a in old:
            with self.assertRaises(ValueError): body_target_authority(g.state, g.registry,
                replace(a.declaration.reference, carrier=BodyReference.capture(copied)), 'paid')

    def test_silence_transform_control_and_zone_changes_retire_old_authority_references(self):
        for name in ('spell.silence', 'spell.form', 'spell.flip', 'spell.bounce'):
            g = self.physical_game(board=True); entity = self.unit(g)
            old = body_target_authorities(g.state, g.registry, BodyReference.capture(entity), 'paid')
            self.play(g, name, entity.id)
            for a in old:
                with self.assertRaises(ValueError): body_target_authority(g.state, g.registry, a.declaration.reference, 'paid')
            if name in ('spell.silence', 'spell.form'):
                self.assertEqual(body_target_authorities(g.state, g.registry, BodyReference.capture(g.state.entities[entity.id]), 'paid'), ())

    def test_pure_authority_query_never_executes_a_registered_target_callback(self):
        for visibility in ('player', 'omniscient'):
            g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('custom.' + visibility,), mana=10, max_mana=10), PlayerSetup('hero'))), physical_registry())
            entity = g.state.entities[g.state.players[1].hand[0]]; before = g.snapshot()
            authorities = body_target_authorities(g.state, g.registry, BodyReference.capture(entity), 'paid')
            self.assertEqual(authorities[0].declaration.contract.target_visibility, visibility)
            self.assertEqual(g.snapshot(), before)

    def test_authority_alone_does_not_remove_heterogeneous_grant_rejection(self):
        r = physical_registry()
        r.register_body_target_binding(BodyTargetBinding('friendly', 'battlecry', 'paid'))
        def bad(c):
            entity = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == 'unit')
            return [GrantBattlecry(BodyReference.capture(entity), 'friendly', c.source_id)]
        r.register_behavior('bad', bad); r.register_card(CardDefinition('bad', 'Bad', CardType.SPELL, on_play='bad'))
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('bad', 'unit'), mana=10, max_mana=10), PlayerSetup('hero'))), r)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
