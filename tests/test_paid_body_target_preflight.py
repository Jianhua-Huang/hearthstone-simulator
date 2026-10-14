"""Real grants and paid-hand facts exercise the independent preflight consumer."""
from dataclasses import replace
import unittest

from hs_sim.engine import (BodyReference, BodyTargetProfile, BodyTargetSelection, PaidBodyTargetRequest,
    CardDefinition, CardType, CardMetadata, CardClass, CostSpec, Game, GrantBattlecry, GrantCombo, IllegalAction,
    Keyword, PaymentType, PlayCard, PlayerSetup, Registry, Scenario, TargetMode, TargetSpec, Zone,
    paid_body_target_plan, preflight_paid_body_targets, validate_paid_body_target_submission)
from hs_sim.engine.body_grants import ConsumeGrantedBody, RemoveGrantedBody
from hs_sim.engine.effects import AddCostModifier, Draw, GainArmor, RequestChoice, ChoiceOption
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.registry import UnsupportedDefinitionError, PlayerRuleContext, RuleContext


PAID = BodyTargetProfile('paid', 'paid_hand', 'manual', 'pre_payment')
GENERATED = BodyTargetProfile('generated', 'generated_whole', 'random', 'generated_acceptance')
DOMAIN = TargetSpec(TargetMode.IF_AVAILABLE, (Zone.BOARD,), (CardType.MINION,), 'friendly')


def registry(condition=None, threshold=3, mode='normal', target_mode=TargetMode.IF_AVAILABLE):
    r = Registry('paid-body-preflight-' + str(condition) + '-' + str(threshold) + '-' + mode + '-' + target_mode.value)
    r.register_body_target_profile(PAID); r.register_body_target_profile(GENERATED)
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=100))
    for name in ('friend', 'enemy'):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=10, metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',))))
    r.register_behavior('body', lambda c: [GainArmor(c.player_id, 1)])
    domain = replace(DOMAIN, mode=target_mode)
    rule = 'any_entity'
    if mode in ('player', 'omniscient', 'never'):
        rule = 'custom'
        def predicate(c):
            if mode == 'never': raise AssertionError('Disabled targeting must not execute a target predicate')
            if mode == 'player':
                assert type(c) is PlayerRuleContext and not hasattr(c, 'state')
                c.source['attack'] = 999
                return c.target is not None
            assert type(c) is RuleContext
            c.state.entities[c.target_id].damage = 999
            return True
        r.register_target_rule(rule, predicate, visibility='player' if mode == 'player' else 'omniscient')
    keywords = {Keyword.COMBO, Keyword.MANATHIRST}
    if condition is not None: keywords.add(Keyword(condition))
    magnetic = mode == 'magnetic'
    if magnetic: keywords.add(Keyword.MAGNETIC)
    r.register_card(CardDefinition('unit', 'Unit', CardType.MINION, cost=2, health=10,
        battlecry='body', combo='body', targeting=domain, target_rule=rule, target_condition=condition,
        manathirst=threshold, keywords=tuple(sorted(keywords)), magnetic_tribes=('mech',) if magnetic else ()))
    for name, threshold in (('low', 5), ('high', 9)):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=10, battlecry='body', combo='body',
            targeting=domain, target_rule=rule, manathirst=threshold, keywords=(Keyword.COMBO, Keyword.MANATHIRST)))
    def setup(c):
        source = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == 'unit')
        return [effect(BodyReference.capture(source), declaration, c.source_id)
                for declaration in ('low', 'high') for effect in (GrantBattlecry, GrantCombo)]
    r.register_behavior('setup', setup)
    r.register_card(CardDefinition('setup', 'Setup', CardType.SPELL, cost=0, on_play='setup'))
    r.register_behavior('tempo', lambda c: [GainArmor(c.player_id, 1)])
    r.register_card(CardDefinition('tempo', 'Tempo', CardType.SPELL, cost=0, on_play='tempo'))
    r.register_behavior('draw', lambda c: [Draw(c.player_id)])
    r.register_card(CardDefinition('draw', 'Draw', CardType.SPELL, cost=1, on_play='draw'))
    r.register_behavior('hold', lambda c: [RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id)])
    r.register_card(CardDefinition('hold', 'Hold', CardType.SPELL, cost=0, on_play='hold'))
    for name, effect in (('consume', ConsumeGrantedBody), ('remove', RemoveGrantedBody)):
        def mutation(c, effect=effect):
            source = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == 'unit')
            body = next(a for a in source.abilities if a.kind == 'battlecry' and a.origin == 'granted')
            return [effect(BodyReference.capture(source), body.id, 'battlecry', c.source_id)]
        r.register_behavior(name, mutation)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=0, on_play=name))
    for name, spec in (('discount', CostSpec(delta=-1, card_ids=('unit',))), ('armor', CostSpec(set_to=3, payment=PaymentType.ARMOR, card_ids=('unit',)))):
        r.register_behavior(name, lambda c, spec=spec: [AddCostModifier(c.player_id, spec, uses_remaining=1, source_id=c.source_id)])
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=0, on_play=name))
    r.register_card(CardDefinition('weapon', 'Weapon', CardType.WEAPON, cost=1, attack=1, durability=3, battlecry='body'))
    return r


class PaidBodyTargetPreflightTests(unittest.TestCase):
    def game(self, *, condition=None, threshold=3, mode='normal', target_mode=TargetMode.IF_AVAILABLE,
             hand=('setup', 'unit', 'tempo', 'consume', 'remove', 'discount', 'armor', 'hold'), board=('friend', 'friend'), mana=6, max_mana=6, deck=(), grant=True):
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board, deck=deck, mana=mana, max_mana=max_mana, armor=10),
            PlayerSetup('hero', board=('enemy',), hand=('enemy',)))), registry(condition, threshold, mode, target_mode))
        if grant: self.play(g, 'setup')
        return g

    def entity(self, g, name):
        return next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == name)

    def play(self, g, name, target=None): g.apply(PlayCard(1, self.entity(g, name).id, target))

    def action(self, g, *, target=True, position=None, branch_id=None, name='unit'):
        board = g.state.players[1].board
        return PlayCard(1, self.entity(g, name).id, board[0] if target and board else None, position, branch_id)

    def request(self, plan):
        chosen = tuple(BodyTargetSelection(r.declaration.reference,
            r.target_choices[(index % len(r.target_choices))] if r.target_choices else None) for index, r in enumerate(plan.requirements))
        return PaidBodyTargetRequest(plan.action, plan.profile_id, chosen)

    def submit(self, g, action=None):
        plan = paid_body_target_plan(g, action or self.action(g), 'paid')
        return preflight_paid_body_targets(g, self.request(plan))

    def test_real_six_body_vector_has_separate_targets_conditions_and_no_payment(self):
        g = self.game(); before = g.snapshot(); submission = self.submit(g)
        self.assertEqual([r.declaration.reference.family for r in submission.plan.requirements], ['battlecry'] * 3 + ['combo'] * 3)
        self.assertEqual([r.conditions.manathirst for r in submission.plan.requirements], [True, True, False] * 2)
        self.assertEqual(len({s.target_id for s in submission.selected}), 2)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(validate_paid_body_target_submission(g, submission), submission)

    def test_reversed_submission_canonicalizes_without_losing_original_order(self):
        g = self.game(); plan = paid_body_target_plan(g, self.action(g), 'paid'); request = self.request(plan)
        shuffled = replace(request, selections=tuple(reversed(request.selections)))
        submission = preflight_paid_body_targets(g, shuffled)
        self.assertEqual(submission.request.selections, shuffled.selections)
        self.assertEqual(submission.selected, request.selections)

    def test_missing_extra_wrong_family_and_stale_body_entries_reject_atomically(self):
        g = self.game(); request = self.request(paid_body_target_plan(g, self.action(g), 'paid')); before = g.snapshot()
        original = request.selections[0]
        for vector in (request.selections[:-1], request.selections + (replace(original, body=replace(original.body, ability_id=99999)),),
                       (replace(original, body=replace(original.body, family='combo')), *request.selections[1:]),
                       (replace(original, body=replace(original.body, carrier=replace(original.body.carrier, zone_epoch=999))), *request.selections[1:])):
            with self.subTest(vector=vector), self.assertRaises(IllegalAction): preflight_paid_body_targets(g, replace(request, selections=vector))
            self.assertEqual(g.snapshot(), before)

    def test_duplicate_alias_and_cross_seat_requests_are_strict(self):
        g = self.game(); request = self.request(paid_body_target_plan(g, self.action(g), 'paid')); before = g.snapshot()
        for delta in ({'selections': (*request.selections, request.selections[0])}, {'action': replace(request.action, player_id=2)}, {'selections': list(request.selections)}):
            with self.subTest(delta=delta), self.assertRaises(ValueError): replace(request, **delta)
        with self.assertRaises(ValueError): replace(request.selections[0], target_id=True)
        self.assertEqual(g.snapshot(), before)

    def test_invalid_enemy_or_missing_required_target_never_pays(self):
        g = self.game(target_mode=TargetMode.REQUIRED); request = self.request(paid_body_target_plan(g, self.action(g), 'paid')); before = g.snapshot()
        for target in (None, g.state.players[2].board[0], 99999):
            bad = replace(request, selections=(replace(request.selections[0], target_id=target), *request.selections[1:]))
            with self.subTest(target=target), self.assertRaises(IllegalAction): preflight_paid_body_targets(g, bad)
            self.assertEqual(g.snapshot(), before)

    def test_empty_if_available_and_optional_domains_keep_explicit_none(self):
        for mode in (TargetMode.IF_AVAILABLE, TargetMode.OPTIONAL):
            g = self.game(target_mode=mode, board=()); submission = self.submit(g)
            self.assertTrue(all(r.target_choices == (None,) for r in submission.plan.requirements))
            self.assertTrue(all(s.target_id is None for s in submission.selected))
        g = self.game(target_mode=TargetMode.REQUIRED, board=())
        with self.assertRaises(IllegalAction): paid_body_target_plan(g, self.action(g), 'paid')

    def test_combo_activation_requires_actual_prior_play(self):
        g = self.game(grant=False); first = self.submit(g)
        self.assertEqual([r.body_active for r in first.plan.requirements], [True, False])
        self.assertEqual(first.plan.requirements[1].target_choices, (None,))
        self.play(g, 'tempo'); later = self.submit(g)
        self.assertEqual([r.body_active for r in later.plan.requirements], [True, True])

    def test_all_five_target_conditions_use_actual_hand_quote_and_crystals(self):
        cases = [('combo', {}, False), ('combo', {}, True), ('outcast', {'hand': ('unit', 'tempo')}, True),
                 ('outcast', {'hand': ('tempo', 'unit', 'tempo')}, False), ('finale', {'mana': 2}, True),
                 ('finale', {'mana': 3}, False), ('manathirst', {'threshold': 5}, True), ('manathirst', {'threshold': 9}, False)]
        for condition, args, active in cases:
            g = self.game(condition=condition, grant=False, **args)
            if condition == 'combo' and active: self.play(g, 'tempo')
            submission = self.submit(g, self.action(g, target=active))
            self.assertEqual(submission.plan.requirements[0].target_active, active)
            if not active: self.assertEqual(submission.plan.requirements[0].target_choices, (None,))
        g = self.game(condition='quickdraw', grant=False)
        self.assertFalse(self.submit(g, self.action(g, target=False)).plan.requirements[0].target_active)
        g = self.game(condition='quickdraw', grant=False, hand=('draw',), deck=('unit',)); self.play(g, 'draw')
        self.assertTrue(self.submit(g).plan.requirements[0].target_active)

    def test_nonmana_payment_does_not_fabricate_finale_or_spend_armor(self):
        g = self.game(mana=2); self.play(g, 'armor'); before = g.snapshot(); submission = self.submit(g)
        self.assertEqual(submission.plan.quote.payment, PaymentType.ARMOR)
        self.assertEqual(submission.plan.quote.amount, 3)
        self.assertFalse(any(r.conditions.finale for r in submission.plan.requirements))
        self.assertEqual(g.snapshot(), before)

    def test_finite_quote_uses_survive_preflight_and_legacy_payment_consumes_once(self):
        g = self.game(); self.play(g, 'discount'); before = g.snapshot()
        for _ in range(3): self.assertEqual(self.submit(g).plan.quote.amount, 1)
        self.assertEqual(g.snapshot(), before); self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, 1)
        g.apply(self.action(g))
        self.assertEqual(g.state.players[1].cost_modifiers, [])

    def test_magnetic_full_board_reserves_normal_fallback_and_captures_host(self):
        g = self.game(mode='magnetic', board=('friend',) * 7)
        action = self.action(g, target=False, position=0); before = g.snapshot(); submission = self.submit(g, action)
        self.assertEqual(submission.plan.magnetic_host.entity_id, g.state.players[1].board[0])
        self.assertTrue(all(r.declaration.profile.magnetic_targets == 'reserve_fallback' for r in submission.plan.requirements))
        self.assertTrue(all(r.target_choices for r in submission.plan.requirements))
        self.assertEqual(g.snapshot(), before)
        with self.assertRaises(IllegalAction): paid_body_target_plan(g, replace(action, position=7), 'paid')
        with self.assertRaises(ValueError): replace(PAID, magnetic_targets='ignore_fallback')

    def test_actual_later_action_invalidates_original_preflight_without_mutation(self):
        g = self.game(); submission = self.submit(g); self.play(g, 'tempo'); before = g.snapshot()
        with self.assertRaises(IllegalAction): validate_paid_body_target_submission(g, submission)
        self.assertEqual(g.snapshot(), before)

    def test_actual_consume_remove_reject_the_old_complete_body_vector(self):
        for name in ('consume', 'remove'):
            g = self.game(); original = self.submit(g); self.play(g, name); before = g.snapshot()
            with self.assertRaises(IllegalAction): preflight_paid_body_targets(g, original.request)
            self.assertEqual(g.snapshot(), before)
            self.assertEqual(len(self.submit(g).selected), 5)

    def test_snapshot_clone_and_real_action_replay_rebuild_identical_preflight(self):
        g = self.game(); expected = self.submit(g)
        for other in (Game.from_snapshot(g.snapshot(), registry()), g.clone(), replay(build_replay(g), registry())):
            self.assertEqual(self.submit(other), expected)

    def test_player_and_omniscient_predicates_receive_detached_correct_contexts(self):
        for mode in ('player', 'omniscient'):
            g = self.game(mode=mode); before = g.snapshot(); self.submit(g)
            self.assertEqual(g.snapshot(), before)

    def test_disabled_condition_never_executes_registered_target_predicate(self):
        g = self.game(condition='manathirst', threshold=9, mode='never', grant=False)
        submission = self.submit(g, self.action(g, target=False))
        self.assertTrue(all(r.target_choices == (None,) for r in submission.plan.requirements))

    def test_wrong_origin_pending_choice_invalid_branch_and_noncarrier_reject(self):
        g = self.game(); before = g.snapshot()
        for profile in ('generated', 'missing'):
            with self.subTest(profile=profile), self.assertRaises(ValueError): paid_body_target_plan(g, self.action(g), profile)
        with self.assertRaises(IllegalAction): paid_body_target_plan(g, self.action(g, branch_id='unknown'), 'paid')
        with self.assertRaises(ValueError): paid_body_target_plan(g, self.action(g, target=False, name='tempo'), 'paid')
        self.assertEqual(g.snapshot(), before)
        self.play(g, 'hold'); before = g.snapshot()
        with self.assertRaises(IllegalAction): paid_body_target_plan(g, self.action(g), 'paid')
        self.assertEqual(g.snapshot(), before)

    def test_weapon_and_both_player_observations_remain_separate_from_host_vector(self):
        g = self.game(hand=('weapon',), grant=False); before = g.snapshot(); observations = [g.for_player(p).observe() for p in (1, 2)]
        action = self.action(g, target=False, name='weapon'); submission = self.submit(g, action)
        self.assertEqual(len(submission.selected), 1); self.assertEqual(submission.selected[0].target_id, None)
        self.assertEqual(submission.plan.requirements[0].declaration.source_kind, CardType.WEAPON)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual([g.for_player(p).observe() for p in (1, 2)], observations)


if __name__ == '__main__': unittest.main()
