"""Structural target rules across real paid bodies, recovery and player boundaries."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from hs_sim.engine import (BodyReference, BodyRootTargetBinding, BodyTargetBinding,
    BodyTargetProfile, BodyTargetSelection, CardClass, CardDefinition, CardMetadata, CardType,
    Game, GrantBattlecry, GrantCombo, Keyword, PaidBodyTargetRequest, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, TargetMode, TargetPredicateSpec,
    TargetSpec, Zone, paid_body_root_target_plan, play_with_body_targets,
    preflight_paid_body_root_targets)
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, GainArmor,
    RandomDamage, RequestChoice, Summon, Transform)
from hs_sim.engine.errors import IllegalAction, ResolutionError, SnapshotError
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.targeting import accepts_target, target_choices


FRIEND = TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,), 'friendly')
ENEMY = replace(FRIEND, relation='enemy')


def registry(mode='normal', *, bound=4, blind=False, callback=False):
    r = Registry('structural-targets-' + mode)
    plain = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    r.register_target_predicate(TargetPredicateSpec('small', health_max=bound))
    r.register_target_predicate(TargetPredicateSpec('dragon', printed_tribes_any=('dragon',)))
    r.register_target_predicate(TargetPredicateSpec('taunt', keywords_all=(Keyword.TAUNT,)))
    r.register_body_target_profile(BodyTargetProfile('paid', 'paid_hand', 'manual', 'pre_payment'))
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30, metadata=plain))
    r.register_card(CardDefinition('beast', 'Beast', CardType.MINION, attack=1, health=4,
        keywords=(Keyword.TAUNT,), metadata=replace(plain, tribes=('beast',))))
    r.register_card(CardDefinition('dragon.unit', 'Dragon', CardType.MINION, attack=2, health=8,
        metadata=replace(plain, tribes=('dragon',))))
    r.register_card(CardDefinition('blank', 'Blank', CardType.MINION, health=4, metadata=plain))
    r.register_card(CardDefinition('unknown', 'Unknown tribes', CardType.MINION, health=4))
    r.register_card(CardDefinition('hidden', 'Hidden', CardType.SPELL, metadata=plain))

    def first(c):
        effects = [GainArmor(c.player_id, 1)]
        if mode == 'transform':
            target = next(i for i in c.state.players[c.player_id].board
                          if c.state.entities[i].card_id == 'dragon.unit')
            effects.append(Transform(target, 'blank'))
        if mode == 'health_change':
            effects.append(Buff(c.target_id, health=5, source_id=c.source_id))
        if mode == 'wait':
            return [RequestChoice(c.player_id,
                (ChoiceOption('ok', 'Continue', tuple(effects)),), c.source_id)]
        return effects

    def combo(c):
        if mode == 'fail':
            return [RandomDamage((c.state.players[2].hero_id,), 1, source_id=c.source_id),
                    Summon(c.player_id, 'not.registered')]
        return [GainArmor(c.player_id, 3), Damage(c.target_id, 1, c.source_id)]

    r.register_behavior('first', first)
    r.register_behavior('dragon.body', lambda c: [GainArmor(c.player_id, 2)])
    r.register_behavior('combo.body', combo)
    r.register_behavior('ordinary', lambda c: [Damage(c.target_id, 1, c.source_id)])
    domain = (TargetSpec(TargetMode.REQUIRED, (Zone.HAND,),
              (CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.HERO), 'enemy')
              if blind else FRIEND)
    target_rule = 'small'
    if callback:
        r.register_target_rule('custom', lambda c: True, visibility='player')
        target_rule = 'custom'
    r.register_card(CardDefinition('unit', 'Carrier', CardType.MINION, cost=2, health=6,
        on_play='ordinary', battlecry='first', targeting=domain,
        target_rule=target_rule, metadata=plain))
    r.register_card(CardDefinition('dragon.body', 'Dragon body', CardType.MINION, health=6,
        battlecry='dragon.body', targeting=FRIEND, target_rule='dragon', metadata=plain))
    r.register_card(CardDefinition('combo.body', 'Combo body', CardType.MINION, health=6,
        combo='combo.body', targeting=FRIEND, target_rule='small',
        keywords=(Keyword.COMBO,), metadata=plain))
    for card_id, family in (('unit', 'battlecry'), ('dragon.body', 'battlecry'), ('combo.body', 'combo')):
        r.register_body_target_binding(BodyTargetBinding(card_id, family, 'paid', carrier_card_ids=('unit',)))
    r.register_body_root_target_binding(BodyRootTargetBinding('unit', 'paid', 'explicit_root', ENEMY, 'small'))

    def setup(c):
        source = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                      if c.state.entities[i].card_id == 'unit')
        return [GrantBattlecry(BodyReference.capture(source), 'dragon.body', c.source_id),
                GrantCombo(BodyReference.capture(source), 'combo.body', c.source_id)]
    r.register_behavior('setup', setup)
    r.register_card(CardDefinition('setup', 'Setup', CardType.SPELL, on_play='setup', metadata=plain))
    return r


def game(mode='normal', *, bound=4, blind=False, callback=False, setup=True,
         enemy_hand='hidden', own_board=('beast', 'dragon.unit')):
    g = Game.from_scenario(Scenario((
        PlayerSetup('hero', hand=('setup', 'unit'), board=own_board, mana=6, max_mana=6),
        PlayerSetup('hero', board=('beast',), hand=(enemy_hand,)))),
        registry(mode, bound=bound, blind=blind, callback=callback))
    if setup:
        g.apply(PlayCard(1, g.state.players[1].hand[0]))
    return g


def action(g):
    source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == 'unit')
    raw = PlayCard(1, source, g.state.players[2].board[0])
    plan = paid_body_root_target_plan(g, raw, 'paid')
    selections = tuple(BodyTargetSelection(row.declaration.reference, row.target_choices[0])
                       for row in plan.bodies.requirements)
    request = PaidBodyTargetRequest(raw, 'paid', selections)
    return play_with_body_targets(preflight_paid_body_root_targets(g, request)), plan


class TargetPredicateTests(unittest.TestCase):
    def test_bounds_and_filter_declarations_are_strict(self):
        invalid = [dict(health_min=True), dict(health_max=1.5), dict(durability_min=-1),
                   dict(health_min=5, health_max=4), dict(printed_tribes_any=['dragon']),
                   dict(printed_tribes_any=('dragon', 'dragon')), dict(printed_tribes_any=('',)),
                   dict(keywords_all=('taunt',)), dict(keywords_none=(Keyword.TAUNT, Keyword.TAUNT)),
                   dict(keywords_all=(Keyword.TAUNT,), keywords_none=(Keyword.TAUNT,))]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                TargetPredicateSpec('invalid', **values)

    def test_registration_rejects_duplicate_callback_impersonation_and_frozen_changes(self):
        r = registry()
        with self.assertRaises(ValueError):
            r.register_target_predicate(TargetPredicateSpec('small'))
        with self.assertRaises(ValueError):
            r.register_target_rule('arbitrary', lambda c: True, visibility='builtin')
        with self.assertRaises(ValueError):
            r.register_target_predicate({'id': 'dictionary'})
        r.freeze()
        with self.assertRaises(ValueError):
            r.register_target_predicate(TargetPredicateSpec('late'))

    def test_rules_combine_current_health_keywords_and_printed_tribes(self):
        r = registry()
        r.register_target_predicate(TargetPredicateSpec('combined', health_min=3, health_max=4,
            printed_tribes_any=('beast', 'dragon'), keywords_all=(Keyword.TAUNT,),
            keywords_none=(Keyword.DIVINE_SHIELD,)))
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('unit',), board=('beast', 'dragon.unit')),
                                        PlayerSetup('hero'))), r)
        state = g.state; source = state.entities[state.players[1].hand[0]]
        definition = replace(r.card('unit'), target_rule='combined')
        self.assertEqual(target_choices(state, r, source, definition), (state.players[1].board[0],))
        target = state.entities[state.players[1].board[0]]
        target.damage = 2
        self.assertEqual(target_choices(state, r, source, definition), ())
        target.damage = 0; target.keywords.add(Keyword.DIVINE_SHIELD)
        self.assertEqual(target_choices(state, r, source, definition), ())
        self.assertEqual(g.state.entities[target.id].health, 4)

    def test_known_empty_tribes_are_excluded_and_unknown_tribes_raise(self):
        g = game(setup=False, own_board=('blank',))
        source = g.state.entities[g.state.players[1].hand[-1]]
        definition = replace(g.registry.card('unit'), target_rule='dragon')
        self.assertEqual(target_choices(g.state, g.registry, source, definition), ())
        unknown = game(setup=False, own_board=('unknown',))
        source = unknown.state.entities[unknown.state.players[1].hand[-1]]
        with self.assertRaisesRegex(ResolutionError, 'known printed tribes'):
            target_choices(unknown.state, unknown.registry, source, definition)

    def test_domains_and_selectable_protections_still_apply(self):
        g = game(setup=False)
        state = g.state; source = state.entities[state.players[1].hand[-1]]
        enemy = state.entities[state.players[2].board[0]]
        definition = replace(g.registry.card('unit'), targeting=ENEMY)
        self.assertTrue(accepts_target(state, g.registry, source, definition, enemy.id))
        enemy.keywords.add(Keyword.STEALTH)
        self.assertFalse(accepts_target(state, g.registry, source, definition, enemy.id))
        friend = state.players[1].board[0]
        self.assertFalse(accepts_target(state, g.registry, source, definition, friend))

    def test_durability_rules_only_read_retained_durability(self):
        r = Registry('durability-rule')
        r.register_target_predicate(TargetPredicateSpec('wear', durability_min=1, durability_max=2))
        r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
        r.register_card(CardDefinition('weapon', 'Weapon', CardType.WEAPON, attack=1, durability=2))
        g = Game.from_scenario(Scenario((PlayerSetup('hero', weapon_card_id='weapon'), PlayerSetup('hero'))), r)
        state = g.state; target = state.entities[state.players[1].weapon_id]
        context = RuleContext(state, state.players[1].hero_id, 1, target.id)
        self.assertTrue(r.target_rule('wear')(context))
        target.durability = 3
        self.assertFalse(r.target_rule('wear')(context))
        self.assertFalse(r.target_rule('wear')(replace(context, target_id=None)))

    def test_predicate_parameters_enter_registry_fingerprint(self):
        self.assertNotEqual(registry(bound=4).fingerprint(), registry(bound=5).fingerprint())
        self.assertEqual(registry().fingerprint(), registry().fingerprint())

    def test_independent_body_domains_and_root_execute_and_pay_once(self):
        g = game(); paid_action, plan = action(g)
        beast, dragon = g.state.players[1].board
        enemy = g.state.players[2].board[0]
        self.assertEqual(plan.root.target_choices, (enemy,))
        self.assertEqual([r.target_choices for r in plan.bodies.requirements], [(beast,), (dragon,), (beast,)])
        before_mana = g.state.players[1].mana
        g.apply(paid_action)
        self.assertEqual(g.state.players[1].mana, before_mana - 2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
        self.assertEqual(g.state.entities[enemy].health, 3)
        self.assertEqual(g.state.entities[beast].health, 3)
        self.assertEqual([r.target_id for r in g.state.battlecry_history], [beast, dragon])
        self.assertEqual([r.target_id for r in g.state.combo_history], [beast])
        self.assertEqual(Game.from_snapshot(g.snapshot(), registry()).snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), g.snapshot())

    def test_invalid_complete_vector_rejects_before_payment_and_preserves_rng(self):
        g = game(); paid_action, _ = action(g)
        bad = replace(paid_action, body_targets=(replace(paid_action.body_targets[0],
            target_id=g.state.players[1].board[1]), *paid_action.body_targets[1:]))
        before = g.snapshot(); history = g.history
        with self.assertRaises(IllegalAction): g.apply(bad)
        self.assertEqual(g.snapshot(), before); self.assertEqual(g.history, history)

    def test_original_printed_face_is_reconstructed_after_actual_transform(self):
        g = game('transform'); paid_action, _ = action(g)
        target = g.state.players[1].board[1]
        g.apply(paid_action)
        self.assertEqual(g.state.entities[target].card_id, 'blank')
        self.assertIsNotNone(g.state.battlecry_history[-1].failure)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 4)
        snapshot = g.snapshot()
        self.assertEqual(Game.from_snapshot(snapshot, registry('transform')).snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), registry('transform')).snapshot(), snapshot)

    def test_current_health_is_rechecked_without_rewriting_original_choices(self):
        g = game('health_change'); paid_action, _ = action(g)
        original_target = paid_action.body_targets[-1].target_id
        g.apply(paid_action)
        self.assertGreater(g.state.entities[original_target].health, 4)
        self.assertIsNotNone(g.state.combo_history[-1].failure)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.assertEqual(Game.from_snapshot(g.snapshot(), registry('health_change')).snapshot(), g.snapshot())

    def test_waiting_restores_clones_replays_and_continues_with_same_targets(self):
        g = game('wait'); paid_action, _ = action(g); g.apply(paid_action)
        snapshot = g.snapshot()
        branches = [g, Game.from_snapshot(snapshot, registry('wait')), g.clone(), replay(build_replay(g), registry('wait'))]
        for branch in branches:
            self.assertEqual(branch.snapshot(), snapshot)
            choice = branch.state.pending_choice
            branch.apply(SelectChoice(1, choice.id, ('ok',)))
        final = g.snapshot()
        for branch in branches:
            self.assertEqual(branch.snapshot(), final)
            for seat in (1, 2):
                self.assertEqual(branch.for_player(seat).observe(), g.for_player(seat).observe())
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, 4)

    def test_failed_later_body_rolls_back_payment_effects_history_and_rng(self):
        g = game('fail'); paid_action, _ = action(g)
        snapshot = g.snapshot(); history = g.history
        with self.assertRaises(ResolutionError): g.apply(paid_action)
        self.assertEqual(g.snapshot(), snapshot); self.assertEqual(g.history, history)

    def test_rehashed_saved_candidates_are_still_recomputed(self):
        g = game(); paid_action, _ = action(g); g.apply(paid_action)
        snapshot = g.snapshot()
        receipt = snapshot['state']['play_history'][-1]['body_targets']
        receipt['body_choices'][0].append(g.state.players[1].board[1])
        excluded = {'schema_version', 'events', 'events_hash', 'state_hash'}
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items() if k not in excluded})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot, registry())

    def test_same_registry_name_with_changed_filter_cannot_restore_saved_acceptance(self):
        g = game(); paid_action, _ = action(g); g.apply(paid_action)
        with self.assertRaises(SnapshotError): Game.from_snapshot(g.snapshot(), registry(bound=5))

    def test_player_json_selections_use_the_same_structural_choices(self):
        g = game(); port = g.for_player(1)
        own = next(p for p in port.observe()['observation']['players'] if p['id'] == 1)
        card = next(c['ref'] for c in own['hand'] if c['card_id'] == 'unit')
        before = g.snapshot(); options = port.independent_targets(card)
        self.assertIsNone(options['error']); self.assertEqual(g.snapshot(), before)
        selected = options['choices'][0]
        command = {'revision': options['revision'], 'action': {'type': 'play_card',
            'card': card, 'target': selected['root_targets'][0],
            'body_targets': [{'body': b['body'], 'target': b['targets'][0]} for b in selected['bodies']]}}
        self.assertTrue(port.submit(command)['accepted'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
        for forbidden in ('profile_id', 'source_json', 'origin_hash', 'registry_fingerprint', 'health_max'):
            self.assertNotIn('"' + forbidden + '"', json.dumps(options))

    def test_enemy_hidden_faces_do_not_change_visible_choices(self):
        games = [game(enemy_hand=card) for card in ('hidden', 'unit')]
        results = []
        for g in games:
            port = g.for_player(1); observation = port.observe()
            own = next(p for p in observation['observation']['players'] if p['id'] == 1)
            card = next(c['ref'] for c in own['hand'] if c['card_id'] == 'unit')
            results.append((observation, port.independent_targets(card)))
        self.assertEqual(*results)

    def test_blind_hand_filter_is_rejected_before_predicate_or_quote(self):
        g = game(blind=True, setup=False); port = g.for_player(1)
        own = next(p for p in port.observe()['observation']['players'] if p['id'] == 1)
        card = next(c['ref'] for c in own['hand'] if c['card_id'] == 'unit')
        source = g.state.entities[g.state.players[1].hand[-1]]
        from hs_sim.engine.body_player_commands import supported
        with (patch('hs_sim.engine.target_predicates.evaluate', side_effect=AssertionError('predicate')),
              patch('hs_sim.engine.costs.quote_cost', side_effect=AssertionError('quote'))):
            from hs_sim.engine.player_api import UnsupportedPlayerRule
            with self.assertRaises(UnsupportedPlayerRule): supported(g, source, 'paid')
        # The ordinary observation legitimately quotes the viewer's own cards;
        # only candidate evaluation must be absent from the refused query.
        with patch('hs_sim.engine.target_predicates.evaluate', side_effect=AssertionError('predicate')):
            self.assertEqual(port.independent_targets(card)['error'], 'unsupported_target_domain')

    def test_unconnected_arbitrary_callbacks_still_fail_before_paid_execution(self):
        g = game(callback=True, setup=False)
        from hs_sim.engine.body_target_origin import require_audited_predicate
        with self.assertRaisesRegex(ValueError, 'audited built-in'):
            require_audited_predicate(g.registry, 'custom')

    def test_ordinary_player_spell_uses_the_same_rule_and_domain(self):
        r = Registry('ordinary-structural-target')
        r.register_target_predicate(TargetPredicateSpec('small', health_max=4))
        r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
        for name, health in (('small.unit', 4), ('large.unit', 8)):
            r.register_card(CardDefinition(name, name, CardType.MINION, health=health))
        r.register_behavior('armor', lambda c: [GainArmor(c.player_id, 1)])
        r.register_card(CardDefinition('spell', 'Spell', CardType.SPELL, cost=1,
            on_play='armor', targeting=FRIEND, target_rule='small'))
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('spell',),
            board=('small.unit', 'large.unit'), mana=2, max_mana=2), PlayerSetup('hero'))), r)
        listing = g.for_player(1).legal_actions()
        self.assertIsNone(listing['error'])
        plays = [a for a in listing['actions'] if a['type'] == 'play_card']
        self.assertEqual(len(plays), 1)
        self.assertTrue(g.for_player(1).submit({'revision': listing['revision'], 'action': plays[0]})['accepted'])
        self.assertEqual(g.state.players[1].mana, 1)

    def test_ordinary_blind_hand_filter_is_rejected_without_hidden_predicate_reads(self):
        r = registry()
        blind = TargetSpec(TargetMode.REQUIRED, (Zone.HAND,),
            (CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.HERO), 'enemy')
        r.register_card(CardDefinition('blind.spell', 'Blind spell', CardType.SPELL,
            on_play='ordinary', targeting=blind, target_rule='small'))
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('blind.spell',)),
            PlayerSetup('hero', hand=('hidden',)))), r)
        from hs_sim.engine.player_api import require_supported_source, UnsupportedPlayerRule
        with patch('hs_sim.engine.target_predicates.evaluate', side_effect=AssertionError('hidden read')):
            with self.assertRaises(UnsupportedPlayerRule):
                require_supported_source(g, g.state.players[1].hand[0])

    def test_required_optional_and_if_available_keep_their_none_policies(self):
        g = game(setup=False, own_board=('dragon.unit',))
        state = g.state; source = state.entities[state.players[1].hand[-1]]
        raw = g.registry.card('unit')
        self.assertEqual(target_choices(state, g.registry, source, raw), ())
        for mode in (TargetMode.OPTIONAL, TargetMode.IF_AVAILABLE):
            definition = replace(raw, targeting=replace(FRIEND, mode=mode))
            self.assertEqual(target_choices(state, g.registry, source, definition), (None,))
        g = game(setup=False)
        state = g.state; source = state.entities[state.players[1].hand[-1]]
        definition = replace(raw, targeting=replace(FRIEND, mode=TargetMode.OPTIONAL))
        self.assertEqual(target_choices(state, g.registry, source, definition), (None, state.players[1].board[0]))


if __name__ == '__main__':
    unittest.main()
