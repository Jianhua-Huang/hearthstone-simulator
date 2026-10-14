"""Real physical grants prove independent root/body legality and original facts."""
from dataclasses import replace
import unittest

from hs_sim.engine import (BodyReference, BodyTargetBinding, BodyRootTargetBinding, BodyTargetSelection,
    PaidBodyTargetRequest, CardDefinition, CardType, ChooseBranch, ChooseOneSpec, EndTurn, Game,
    GrantBattlecry, GrantCombo, IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario,
    TargetSpec, TargetMode, Zone, paid_body_target_plan, paid_body_root_target_plan,
    preflight_paid_body_root_targets, validate_paid_body_root_target_submission)
from hs_sim.engine.effects import GainArmor
from hs_sim.engine.registry import PlayerRuleContext, RuleContext
from hs_sim.engine.replay import build_replay, replay
from test_paid_body_target_preflight import registry as base_registry


ENEMY = TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,), 'enemy')
FRIEND = replace(ENEMY, relation='friendly')


def registry(mode='explicit_root', *, condition=None, threshold=None, visibility='builtin', magnetic=False):
    r = base_registry(mode='magnetic' if magnetic else 'normal')
    r.register_behavior('ordinary', lambda c: [GainArmor(c.player_id, 1)])
    r.register_card(replace(r.card('unit'), id='hybrid', name='Hybrid', on_play='ordinary'))
    r.register_card(CardDefinition('untargeted', 'Untargeted', CardType.MINION, health=10, battlecry='body'))
    branches = ChooseOneSpec((ChooseBranch('friend', 'Friend', 'ordinary', FRIEND),
        ChooseBranch('enemy', 'Enemy', 'ordinary', ENEMY)), ChooseBranch('both', 'Both', 'ordinary'))
    r.register_card(CardDefinition('choice', 'Choice', CardType.MINION, cost=2, health=10, choose_one=branches))
    r.register_card(CardDefinition('both', 'Both source', CardType.MINION, health=10, choose_both=True))
    def setup(c):
        e = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == 'hybrid')
        return [effect(BodyReference.capture(e), declaration, c.source_id) for declaration in ('low', 'high') for effect in (GrantBattlecry, GrantCombo)]
    r.register_behavior('hybrid.setup', setup)
    r.register_card(CardDefinition('hybrid.setup', 'Setup', CardType.SPELL, on_play='hybrid.setup'))
    def choice_setup(c):
        e = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == 'choice')
        return [GrantBattlecry(BodyReference.capture(e), 'untargeted', c.source_id)]
    r.register_behavior('choice.setup', choice_setup)
    r.register_card(CardDefinition('choice.setup', 'Setup', CardType.SPELL, on_play='choice.setup'))
    for card_id in ('unit', 'hybrid', 'low', 'high', 'untargeted', 'weapon'):
        for family in ('battlecry', 'combo'):
            if getattr(r.card(card_id), family) is not None:
                r.register_body_target_binding(BodyTargetBinding(card_id, family, 'paid'))
    rule = 'any_entity'
    if visibility != 'builtin':
        rule = 'root.custom'
        def predicate(c):
            if visibility == 'never': raise AssertionError('Inactive root targeting must not invoke predicates')
            if visibility == 'player':
                assert type(c) is PlayerRuleContext and not hasattr(c, 'state')
                c.source['attack'] = 999
                return c.target is not None
            assert type(c) is RuleContext
            c.state.entities[c.target_id].damage = 999
            return True
        r.register_target_rule(rule, predicate, visibility='player' if visibility in ('player', 'never') else 'omniscient')
    if mode == 'explicit_root':
        r.register_body_root_target_binding(BodyRootTargetBinding('hybrid', 'paid', mode,
            ENEMY, rule, condition, threshold))
    else:
        r.register_body_root_target_binding(BodyRootTargetBinding('hybrid', 'paid', mode))
    for card_id, policy in (('unit', 'body_only'), ('weapon', 'body_only'), ('choice', 'preserve_root')):
        r.register_body_root_target_binding(BodyRootTargetBinding(card_id, 'paid', policy))
    return r


class BodyRootTargetTests(unittest.TestCase):
    def game(self, *, r=None, name='hybrid', grant=True, hand=None, board=('friend', 'friend'), mana=6, max_mana=6, deck=()):
        setup = 'hybrid.setup' if name == 'hybrid' else 'choice.setup' if name == 'choice' else 'setup'
        hand = hand or (setup, name, 'tempo', 'consume', 'remove', 'discount', 'armor', 'hold')
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board, deck=deck, mana=mana, max_mana=max_mana, armor=10),
            PlayerSetup('hero', board=('enemy',), hand=('enemy',)))), r or registry())
        if grant: self.play(g, setup)
        return g

    def entity(self, g, name):
        return next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == name)

    def play(self, g, name, target=None): g.apply(PlayCard(1, self.entity(g, name).id, target))

    def action(self, g, name='hybrid', *, target=None, branch=None, position=None):
        return PlayCard(1, self.entity(g, name).id, target, position, branch)

    def request(self, plan):
        return PaidBodyTargetRequest(plan.bodies.action, plan.bodies.profile_id,
            tuple(BodyTargetSelection(r.declaration.reference,
                r.target_choices[i % len(r.target_choices)] if r.target_choices else None)
                for i, r in enumerate(plan.bodies.requirements)))

    def plan(self, g, action): return paid_body_root_target_plan(g, action, 'paid')

    def test_ordinary_enemy_root_is_separate_from_six_real_friendly_body_slots(self):
        g = self.game(); target = g.state.players[2].board[0]; action = self.action(g, target=target)
        before = g.snapshot(); observations = [g.for_player(p).observe() for p in (1, 2)]
        with self.assertRaises(IllegalAction): g.validate(action)
        plan = self.plan(g, action); submission = preflight_paid_body_root_targets(g, self.request(plan))
        self.assertEqual(plan.root.target_choices, (target,)); self.assertEqual(len(plan.root.root_abilities), 1)
        self.assertEqual(len(plan.authorities), 6)
        self.assertEqual(len({s.target_id for s in submission.selected}), 2)
        self.assertTrue(all(s.target_id in g.state.players[1].board for s in submission.selected))
        self.assertEqual([r.conditions.manathirst for r in plan.bodies.requirements], [True, True, False] * 2)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual([g.for_player(p).observe() for p in (1, 2)], observations)

    def test_body_only_can_omit_redundant_root_but_cannot_omit_body_targets(self):
        g = self.game(name='unit'); action = self.action(g, 'unit'); before = g.snapshot()
        with self.assertRaises(IllegalAction): paid_body_target_plan(g, action, 'paid')
        plan = self.plan(g, action); self.assertEqual(plan.root.target_choices, (None,)); self.assertEqual(plan.root.root_abilities, ())
        request = self.request(plan); self.assertEqual(len(preflight_paid_body_root_targets(g, request).selected), 6)
        with self.assertRaises(IllegalAction): preflight_paid_body_root_targets(g, replace(request, selections=request.selections[:-1]))
        with self.assertRaises(IllegalAction): preflight_paid_body_root_targets(g, replace(request,
            selections=(replace(request.selections[0], target_id=None), *request.selections[1:])))
        with self.assertRaises(IllegalAction): g.apply(action)
        self.assertEqual(g.snapshot(), before)

    def test_preserve_root_keeps_the_original_target_contract(self):
        g = self.game(r=registry('preserve_root')); friend = g.state.players[1].board[0]
        plan = self.plan(g, self.action(g, target=friend)); self.assertEqual(plan.root.targeting.relation, 'friendly')
        self.assertEqual(plan.root.target_choices, tuple(g.state.players[1].board))
        for target in (None, g.state.players[2].board[0]):
            with self.assertRaises(IllegalAction): self.plan(g, self.action(g, target=target))

    def test_root_and_body_targets_never_substitute_for_each_other(self):
        g = self.game(); action = self.action(g, target=g.state.players[2].board[0]); request = self.request(self.plan(g, action)); before = g.snapshot()
        bad = replace(request, selections=(replace(request.selections[0], target_id=action.target_id), *request.selections[1:]))
        with self.assertRaises(IllegalAction): preflight_paid_body_root_targets(g, bad)
        with self.assertRaises(IllegalAction): self.plan(g, self.action(g, target=g.state.players[1].board[0]))
        self.assertEqual(g.snapshot(), before)

    def test_root_manathirst_uses_its_own_threshold_independent_of_every_body(self):
        for threshold, active in ((5, True), (9, False)):
            g = self.game(r=registry(condition='manathirst', threshold=threshold))
            plan = self.plan(g, self.action(g, target=g.state.players[2].board[0] if active else None))
            self.assertEqual(plan.root.conditions.manathirst, active)
            self.assertEqual(plan.root.conditions.manathirst_threshold, threshold)
            self.assertEqual([r.conditions.manathirst for r in plan.bodies.requirements], [True, True, False] * 2)
            if not active: self.assertEqual(plan.root.target_choices, (None,))

    def test_root_combo_outcast_finale_quickdraw_keep_actual_original_facts(self):
        cases = [('combo', {}, False), ('combo', {}, True), ('outcast', {'hand': ('hybrid', 'tempo')}, True),
            ('outcast', {'hand': ('tempo', 'hybrid', 'tempo')}, False), ('finale', {'mana': 2}, True),
            ('finale', {'mana': 3}, False), ('quickdraw', {}, False)]
        for condition, args, active in cases:
            g = self.game(r=registry(condition=condition), grant=False, **args)
            if condition == 'combo' and active: self.play(g, 'tempo')
            target = g.state.players[2].board[0] if active else None
            plan = self.plan(g, self.action(g, target=target))
            self.assertEqual(getattr(plan.root.conditions, condition), active)
            self.assertEqual(plan.root.target_active, active)
        g = self.game(r=registry(condition='quickdraw'), grant=False, hand=('draw',), deck=('hybrid',))
        self.play(g, 'draw')
        plan = self.plan(g, self.action(g, target=g.state.players[2].board[0]))
        self.assertTrue(plan.root.conditions.quickdraw)
        self.assertTrue(plan.root.target_active)


    def test_disabled_root_predicate_is_not_invoked_and_other_permissions_are_detached(self):
        g = self.game(r=registry(condition='manathirst', threshold=9, visibility='never'))
        before = g.snapshot(); self.plan(g, self.action(g)); self.assertEqual(g.snapshot(), before)
        for visibility in ('player', 'omniscient'):
            g = self.game(r=registry(visibility=visibility)); before = g.snapshot()
            plan = self.plan(g, self.action(g, target=g.state.players[2].board[0]))
            self.assertEqual(plan.root.target_visibility, visibility); self.assertEqual(g.snapshot(), before)

    def test_choose_one_preserves_the_exact_selected_branch_and_its_target_domain(self):
        g = self.game(name='choice')
        for branch, player_id in (('friend', 1), ('enemy', 2)):
            target = g.state.players[player_id].board[0]; plan = self.plan(g, self.action(g, 'choice', target=target, branch=branch))
            self.assertEqual(plan.root.branch_id, branch); self.assertEqual(plan.root.branch_behavior_id, 'ordinary')
            self.assertEqual(plan.root.targeting.relation, 'friendly' if player_id == 1 else 'enemy')
            self.assertEqual(len(plan.authorities), 1); self.assertEqual(plan.bodies.requirements[0].target_choices, (None,))
        for branch in (None, 'unknown', 'both'):
            with self.assertRaises(IllegalAction): self.plan(g, self.action(g, 'choice', branch=branch))

    def test_choose_both_policy_and_branch_space_remain_part_of_common_legality(self):
        g = self.game(name='choice', board=('both', 'friend'))
        plan = self.plan(g, self.action(g, 'choice', branch='both')); self.assertEqual(plan.root.target_choices, (None,))
        with self.assertRaises(IllegalAction): self.plan(g, self.action(g, 'choice', target=g.state.players[1].board[1], branch='friend'))
        g = self.game(name='choice', board=('friend',) * 7)
        with self.assertRaises(IllegalAction): self.plan(g, self.action(g, 'choice', target=g.state.players[2].board[0], branch='enemy'))

    def test_affordability_position_turn_pending_and_source_checks_are_not_bypassed(self):
        g = self.game(mana=1); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.plan(g, self.action(g, target=g.state.players[2].board[0]))
        self.assertEqual(g.snapshot(), before)
        g = self.game(); valid = self.action(g, target=g.state.players[2].board[0])
        for action in (replace(valid, player_id=2), replace(valid, position=99), replace(valid, entity_id=99999)):
            with self.assertRaises(IllegalAction): self.plan(g, action)
        self.play(g, 'hold'); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.plan(g, valid)
        self.assertEqual(g.snapshot(), before)

    def test_magnetic_full_board_reserves_normal_root_and_body_requirements(self):
        g = self.game(r=registry(magnetic=True), board=('friend',) * 7)
        action = self.action(g, target=g.state.players[2].board[0], position=0); before = g.snapshot()
        plan = self.plan(g, action)
        self.assertEqual(plan.bodies.magnetic_host.entity_id, g.state.players[1].board[0])
        self.assertEqual(plan.root.target_choices, (g.state.players[2].board[0],)); self.assertEqual(len(plan.bodies.requirements), 6)
        with self.assertRaises(IllegalAction): self.plan(g, replace(action, target_id=None))
        with self.assertRaises(IllegalAction): self.plan(g, replace(action, position=7))
        self.assertEqual(g.snapshot(), before)

    def test_snapshot_clone_real_replay_and_later_action_obligations_recompute(self):
        g = self.game(); a = self.action(g, target=g.state.players[2].board[0]); s = preflight_paid_body_root_targets(g, self.request(self.plan(g, a)))
        for other in (Game.from_snapshot(g.snapshot(), registry()), g.clone(), replay(build_replay(g), registry())):
            self.assertEqual(validate_paid_body_root_target_submission(other, s), s)
        self.play(g, 'tempo'); before = g.snapshot()
        with self.assertRaises(IllegalAction): validate_paid_body_root_target_submission(g, s)
        self.assertEqual(g.snapshot(), before)

    def test_registry_cannot_erase_payloads_or_bind_generated_root_policies(self):
        r = base_registry(); r.register_behavior('ordinary', lambda c: [GainArmor(c.player_id, 1)])
        r.register_card(replace(r.card('unit'), id='hybrid', on_play='ordinary'))
        for binding in (BodyRootTargetBinding('hybrid', 'paid', 'body_only'),
                        BodyRootTargetBinding('unit', 'paid', 'explicit_root', ENEMY),
                        BodyRootTargetBinding('unit', 'generated', 'body_only'),
                        BodyRootTargetBinding('tempo', 'paid', 'preserve_root')):
            with self.assertRaises(ValueError): r.register_body_root_target_binding(binding)
        r.register_body_root_target_binding(BodyRootTargetBinding('unit', 'paid', 'body_only')); old = r.fingerprint()
        with self.assertRaises(ValueError): r.register_body_root_target_binding(BodyRootTargetBinding('unit', 'paid', 'preserve_root'))
        self.assertEqual(r.fingerprint(), old)
        with self.assertRaises(TypeError): r.body_root_target_bindings[('x', 'paid')] = None
        r.freeze()
        with self.assertRaises(ValueError): r.register_body_root_target_binding(BodyRootTargetBinding('weapon', 'paid', 'body_only'))

    def test_missing_root_policy_and_forged_root_plan_cannot_borrow_known_body_permission(self):
        r = base_registry()
        for family in ('battlecry', 'combo'): r.register_body_target_binding(BodyTargetBinding('unit', family, 'paid'))
        g = self.game(r=r, name='unit', grant=False); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.plan(g, self.action(g, 'unit'))
        self.assertEqual(g.snapshot(), before)
        g = self.game(); request = self.request(self.plan(g, self.action(g, target=g.state.players[2].board[0])))
        s = preflight_paid_body_root_targets(g, request)
        forged = replace(s.plan.root, binding=replace(s.plan.root.binding, target_rule='any_character'))
        bad = replace(s, plan=replace(s.plan, root=forged)); before = g.snapshot()
        with self.assertRaises(IllegalAction): validate_paid_body_root_target_submission(g, bad)
        self.assertEqual(g.snapshot(), before)


if __name__ == '__main__': unittest.main()
