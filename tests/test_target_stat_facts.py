"""Real target stat acceptance, live changes, compact origins and recovery."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (BodyReference, BodyRootTargetBinding, BodyTargetBinding, BodyTargetProfile,
    BodyTargetSelection, CardDefinition, CardType, Game, GrantBattlecry, GrantCombo,
    Keyword, PaidBodyTargetRequest, PlayCard, PlayerSetup, Scenario, SelectChoice,
    StatRelationSpec, TargetMode, TargetPredicateSpec, TargetSpec, Zone,
    paid_body_root_target_plan, play_with_body_targets, preflight_paid_body_root_targets)
from hs_sim.engine.effects import Buff, ChoiceOption, Damage, GainArmor, Heal, RequestChoice
from hs_sim.engine.errors import IllegalAction, SnapshotError
from hs_sim.engine.body_target_origin import entity_fact, origin_hash
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.model import RewindSpec
from hs_sim.engine.targeting import target_choices
from test_target_predicates import FRIEND, ENEMY, registry as base_registry


def registry(mode='normal', *, limit=1):
    r = base_registry('fail' if mode == 'fail' else 'normal')
    r.register_target_predicate(TargetPredicateSpec('stat.target', attack_max=limit,
        max_health_min=4, max_health_max=4, damage_min=1, damage_max=2, damaged=True))
    r.register_target_predicate(TargetPredicateSpec('stat.root', attack_max=1,
        max_health_min=4, max_health_max=4, damaged=False))
    r.register_card(CardDefinition('health.attack', 'Health derived attack', CardType.MINION,
        health=4, stat_relations=(StatRelationSpec(),), metadata=r.card('beast').metadata))
    r.register_card(replace(r.card('beast'), id='all.tribes', name='All tribes',
        metadata=replace(r.card('beast').metadata, tribes=('all',))))

    def first(c):
        effects = [GainArmor(c.player_id, 1)]
        if mode == 'attack_change': effects.append(Buff(c.target_id, attack=3, source_id=c.source_id))
        if mode == 'max_change': effects.append(Buff(c.target_id, health=5, source_id=c.source_id))
        if mode == 'heal': effects.append(Heal(c.target_id, 100, c.source_id))
        if mode == 'wait':
            return [RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', tuple(effects)),), c.source_id)]
        return effects

    r.register_behavior('stat.first', first)
    r.register_card(replace(r.card('unit'), id='stat.unit', name='Stat carrier',
        battlecry='stat.first', target_rule='stat.target'))
    r.register_card(replace(r.card('dragon.body'), id='stat.dragon', name='Stat dragon body'))
    r.register_card(replace(r.card('combo.body'), id='stat.combo', name='Stat combo', target_rule='stat.target'))
    for name, family in (('stat.unit', 'battlecry'), ('stat.dragon', 'battlecry'), ('stat.combo', 'combo')):
        r.register_body_target_binding(BodyTargetBinding(name, family, 'paid', carrier_card_ids=('stat.unit',)))
    r.register_body_root_target_binding(BodyRootTargetBinding('stat.unit', 'paid', 'explicit_root', ENEMY, 'stat.root'))

    def setup(c):
        source = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                      if c.state.entities[i].card_id == 'stat.unit')
        target = c.state.players[c.player_id].board[0]
        return [Damage(target, 1, c.source_id),
                GrantBattlecry(BodyReference.capture(source), 'stat.dragon', c.source_id),
                GrantCombo(BodyReference.capture(source), 'stat.combo', c.source_id)]

    r.register_behavior('stat.setup', setup)
    r.register_card(CardDefinition('stat.setup', 'Setup stats', CardType.SPELL, on_play='stat.setup'))
    return r


def game(mode='normal', *, limit=1, victim='beast', enemy_hand='hidden'):
    g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('stat.setup', 'stat.unit'),
            board=(victim, 'dragon.unit'), mana=6, max_mana=6),
        PlayerSetup('hero', board=('beast',), hand=(enemy_hand,)))), registry(mode, limit=limit))
    g.apply(PlayCard(1, g.state.players[1].hand[0]))
    return g


def action(g):
    source = g.state.players[1].hand[0]
    raw = PlayCard(1, source, g.state.players[2].board[0])
    plan = paid_body_root_target_plan(g, raw, 'paid')
    request = PaidBodyTargetRequest(raw, 'paid', tuple(BodyTargetSelection(
        row.declaration.reference, row.target_choices[0]) for row in plan.bodies.requirements))
    return play_with_body_targets(preflight_paid_body_root_targets(g, request)), plan


def rehash(snapshot, *, receipt_hash=True):
    if receipt_hash:
        receipt = snapshot['state']['play_history'][-1]['body_targets']
        receipt['origin_hash'] = canonical_hash(receipt['origin'])
    excluded = {'schema_version', 'events', 'events_hash', 'state_hash'}
    snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items() if k not in excluded})
    return snapshot


class TargetStatFactTests(unittest.TestCase):
    def roundtrip(self, g, mode='normal', *, limit=1):
        snapshot = g.snapshot()
        for other in (Game.from_snapshot(snapshot, registry(mode, limit=limit)),
                      g.clone(), replay(build_replay(g), registry(mode, limit=limit))):
            self.assertEqual(other.snapshot(), snapshot)
            for seat in (1, 2):
                self.assertEqual(other.for_player(seat).observe(), g.for_player(seat).observe())

    def test_new_stat_filters_have_exact_bounds_and_damaged_contract(self):
        invalid = [dict(attack_min=True), dict(attack_max=1.5), dict(attack_min=4, attack_max=3),
            dict(max_health_min=True), dict(max_health_min=5, max_health_max=4),
            dict(damage_min=-1), dict(damage_max=True), dict(damage_min=2, damage_max=1),
            dict(damaged=1), dict(damaged='yes'), dict(damaged=False, damage_min=1),
            dict(damaged=True, damage_max=0)]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                TargetPredicateSpec('invalid', **values)
        TargetPredicateSpec('valid', attack_min=0, attack_max=0, damage_min=0, damaged=False)

    def test_current_stat_filters_intersect_and_do_not_use_remaining_health_as_maximum(self):
        g = game(); paid_action, plan = action(g)
        small, large = g.state.players[1].board
        self.assertEqual([row.target_choices for row in plan.bodies.requirements], [(small,), (large,), (small,)])
        before = g.snapshot()
        self.assertEqual(before['state']['entities'][str(small)]['damage'], 1)
        self.assertEqual((g.state.entities[small].health, g.state.entities[small].max_health), (3, 4))
        self.assertEqual(g.snapshot(), before)

    def test_full_health_and_each_numeric_boundary_are_evaluated_separately(self):
        g = game(); state = g.state
        source = state.entities[state.players[1].hand[0]]; target = state.players[1].board[0]
        values = [dict(attack_min=1, attack_max=1), dict(max_health_min=4, max_health_max=4),
                  dict(damage_min=1, damage_max=1), dict(damaged=True)]
        r = registry()
        for index, filters in enumerate(values):
            name = 'bound.' + str(index)
            r.register_target_predicate(TargetPredicateSpec(name, **filters))
            definition = replace(r.card('unit'), target_rule=name)
            self.assertEqual(target_choices(state, r, source, definition), (target,))
        r.register_target_predicate(TargetPredicateSpec('full', damaged=False))
        full = replace(r.card('unit'), target_rule='full')
        self.assertEqual(target_choices(state, r, source, full), (state.players[1].board[1],))

    def test_actual_payment_and_all_bodies_use_their_own_original_stats(self):
        g = game(); paid_action, _ = action(g); g.apply(paid_action)
        small, large = g.state.players[1].board[:2]
        record = g.state.play_history[-1]
        fact = next(f for f in record.body_targets.origin.entities if f.id == small)
        self.assertEqual((fact.attack, fact.max_health, fact.damage, fact.health), (1, 4, 1, 3))
        self.assertEqual(g.state.entities[small].damage, 2)
        self.assertEqual(g.state.players[1].mana, 4)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
        self.assertEqual([r.target_id for r in g.state.battlecry_history], [small, large])
        self.assertEqual([r.target_id for r in g.state.combo_history], [small])
        self.roundtrip(g)

    def test_attack_buff_skips_later_body_and_does_not_rewrite_original_attack(self):
        g = game('attack_change'); paid_action, _ = action(g); g.apply(paid_action)
        target = paid_action.body_targets[0].target_id
        self.assertEqual(g.state.entities[target].attack, 4)
        fact = next(f for f in g.state.play_history[-1].body_targets.origin.entities if f.id == target)
        self.assertEqual(fact.attack, 1)
        self.assertIsNotNone(g.state.combo_history[-1].failure)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.roundtrip(g, 'attack_change')

    def test_maximum_health_buff_preserves_old_maximum_and_damage(self):
        g = game('max_change'); paid_action, _ = action(g); g.apply(paid_action)
        target = paid_action.body_targets[0].target_id
        self.assertEqual((g.state.entities[target].max_health, g.state.entities[target].health), (9, 8))
        self.assertIsNotNone(g.state.combo_history[-1].failure)
        fact = next(f for f in g.state.play_history[-1].body_targets.origin.entities if f.id == target)
        self.assertEqual((fact.max_health, fact.health, fact.damage), (4, 3, 1))
        self.roundtrip(g, 'max_change')

    def test_healing_changes_live_damaged_eligibility_but_retains_original_damage(self):
        g = game('heal'); paid_action, _ = action(g); g.apply(paid_action)
        target = paid_action.body_targets[0].target_id
        self.assertEqual(g.state.entities[target].damage, 0)
        self.assertIsNotNone(g.state.combo_history[-1].failure)
        fact = next(f for f in g.state.play_history[-1].body_targets.origin.entities if f.id == target)
        self.assertEqual(fact.damage, 1)
        self.roundtrip(g, 'heal')

    def test_derived_attack_is_captured_as_current_attack_not_printed_base(self):
        g = game(limit=3, victim='health.attack'); paid_action, _ = action(g)
        target = paid_action.body_targets[0].target_id
        self.assertEqual((g.state.entities[target].base_attack, g.state.entities[target].attack), (0, 3))
        g.apply(paid_action)
        fact = next(f for f in g.state.play_history[-1].body_targets.origin.entities if f.id == target)
        self.assertEqual(fact.attack, 3)
        self.assertEqual(g.state.entities[target].attack, 2)
        self.roundtrip(g, limit=3)

    def test_health_damage_invariants_are_enforced_even_without_candidate_rehash(self):
        g = game(); fact = entity_fact(g.state.entities[g.state.players[1].board[0]])
        for changes in (dict(attack=True), dict(damage=True), dict(max_health=True),
                        dict(damage=-1), dict(health=4), dict(max_health=5), dict(attack=-1)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(fact, **changes)

    def test_dead_original_fact_can_retain_signed_health_and_maximum(self):
        g = game(); entity = deepcopy(g.state.entities[g.state.players[1].board[0]])
        entity.base_health = -2; entity.health_bonus = 0; entity.aura_health = 0; entity.damage = 3
        fact = entity_fact(entity)
        self.assertEqual((fact.max_health, fact.damage, fact.health), (-2, 3, -5))
        fact.__post_init__()

    def test_rehashed_attack_fact_conflicting_with_original_candidates_is_rejected(self):
        g = game(); paid_action, _ = action(g); g.apply(paid_action)
        snapshot = g.snapshot(); receipt = snapshot['state']['play_history'][-1]['body_targets']
        target = paid_action.body_targets[0].target_id
        fact = next(f for f in receipt['origin']['entities'] if f['id'] == target); fact['attack'] = 4
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(snapshot), registry())

    def test_missing_new_facts_do_not_silently_use_zero_defaults(self):
        g = game(); paid_action, _ = action(g); g.apply(paid_action)
        for field in ('attack', 'max_health', 'damage'):
            snapshot = g.snapshot(); receipt = snapshot['state']['play_history'][-1]['body_targets']
            receipt['origin']['entities'][0].pop(field)
            with self.subTest(field=field), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(snapshot), registry())

    def test_original_source_scalar_fact_must_match_complete_source_entity(self):
        g = game(); paid_action, _ = action(g); g.apply(paid_action)
        snapshot = g.snapshot(); receipt = snapshot['state']['play_history'][-1]['body_targets']
        fact = next(f for f in receipt['origin']['entities'] if f['id'] == paid_action.entity_id)
        fact['attack'] += 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(snapshot), registry())

    def test_waiting_rebuilds_all_stat_inputs_and_continues_each_restored_branch(self):
        g = game('wait'); paid_action, _ = action(g); g.apply(paid_action); snapshot = g.snapshot()
        branches = [g, Game.from_snapshot(snapshot, registry('wait')), g.clone(), replay(build_replay(g), registry('wait'))]
        for branch in branches:
            self.assertEqual(branch.snapshot(), snapshot)
            choice = branch.state.pending_choice
            branch.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))
        for branch in branches:
            self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertEqual(g.state.players[1].mana, 4)

    def test_failed_later_body_rolls_back_stats_payment_rng_and_history(self):
        g = game('fail'); paid_action, _ = action(g); snapshot = g.snapshot(); history = g.history
        from hs_sim.engine.errors import ResolutionError
        with self.assertRaises(ResolutionError): g.apply(paid_action)
        self.assertEqual(g.snapshot(), snapshot); self.assertEqual(g.history, history)

    def test_old131_schema_is_rejected_before_any_missing_fact_interpretation(self):
        g = game(); snapshot = g.snapshot(); self.assertEqual(snapshot['schema_version'], 266)
        snapshot['schema_version'] = 131
        with self.assertRaisesRegex(SnapshotError, '1 through 265'):
            Game.from_snapshot(snapshot, registry())

    def test_all_tribes_matches_any_requested_printed_tribe(self):
        r = registry()
        r.register_target_predicate(TargetPredicateSpec('beast.or.naga', printed_tribes_any=('beast', 'naga')))
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('unit',), board=('all.tribes', 'dragon.unit')),
                                        PlayerSetup('hero'))), r)
        state = g.state; source = state.entities[state.players[1].hand[0]]
        definition = replace(r.card('unit'), target_rule='beast.or.naga')
        self.assertEqual(target_choices(state, r, source, definition), (state.players[1].board[0],))

    def test_real_all_tribes_body_target_acceptance_restores_after_current_damage(self):
        g = game(victim='all.tribes'); paid_action, _ = action(g); g.apply(paid_action)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
        self.roundtrip(g)

    def test_enemy_hidden_stats_do_not_change_visible_stat_target_options(self):
        results = []
        for hidden in ('hidden', 'health.attack'):
            g = game(enemy_hand=hidden); port = g.for_player(1); observation = port.observe()
            own = next(p for p in observation['observation']['players'] if p['id'] == 1)
            card = next(c['ref'] for c in own['hand'] if c['card_id'] == 'stat.unit')
            options = port.independent_targets(card)
            self.assertIsNone(options['error']); results.append((observation, options))
            for field in ('max_health_min', 'damage_min', 'origin_hash', 'source_json'):
                self.assertNotIn('"' + field + '"', json.dumps(options))
        self.assertEqual(*results)

    def test_actual_player_json_uses_shared_stat_candidates_and_one_payment(self):
        g = game(); port = g.for_player(1); own = next(p for p in port.observe()['observation']['players'] if p['id'] == 1)
        card = next(c['ref'] for c in own['hand'] if c['card_id'] == 'stat.unit')
        options = port.independent_targets(card); selected = options['choices'][0]
        command = {'revision': options['revision'], 'action': {'type': 'play_card', 'card': card,
            'target': selected['root_targets'][0],
            'body_targets': [{'body': b['body'], 'target': b['targets'][0]} for b in selected['bodies']]}}
        self.assertTrue(port.submit(command)['accepted'])
        self.assertEqual(g.state.players[1].mana, 4)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)

    def test_one_real_rewind_retry_recaptures_stats_and_restores_each_waiting_branch(self):
        def factory():
            r = registry()
            profile = 'stat.retry'
            r.register_body_target_profile(BodyTargetProfile(profile, 'paid_hand', 'manual',
                'pre_payment', retry_targets='reuse_original_selection'))
            r.register_card(replace(r.card('stat.unit'), id='stat.retry.unit', name='Retry stat carrier',
                keywords=(Keyword.REWIND,), rewind=RewindSpec(retries=1)))
            r.register_card(replace(r.card('stat.dragon'), id='retry.dragon', name='Retry dragon body'))
            r.register_card(replace(r.card('stat.combo'), id='retry.combo', name='Retry combo body'))
            for name, family in (('stat.retry.unit', 'battlecry'), ('retry.dragon', 'battlecry'), ('retry.combo', 'combo')):
                r.register_body_target_binding(BodyTargetBinding(name, family, profile, carrier_card_ids=('stat.retry.unit',)))
            r.register_body_root_target_binding(BodyRootTargetBinding('stat.retry.unit', profile, 'explicit_root', ENEMY, 'stat.root'))

            def setup(c):
                source = next(c.state.entities[i] for i in c.state.players[1].hand
                              if c.state.entities[i].card_id == 'stat.retry.unit')
                return [Damage(c.state.players[1].board[0], 1, c.source_id),
                    GrantBattlecry(BodyReference.capture(source), 'retry.dragon', c.source_id),
                    GrantCombo(BodyReference.capture(source), 'retry.combo', c.source_id)]
            r.register_behavior('retry.setup', setup)
            r.register_card(CardDefinition('retry.setup', 'Setup retry', CardType.SPELL, on_play='retry.setup'))
            return r

        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('retry.setup', 'stat.retry.unit'),
            board=('beast', 'dragon.unit'), mana=6, max_mana=6), PlayerSetup('hero', board=('beast',)))), factory())
        g.apply(PlayCard(1, g.state.players[1].hand[0]))
        raw = PlayCard(1, g.state.players[1].hand[0], g.state.players[2].board[0])
        plan = paid_body_root_target_plan(g, raw, 'stat.retry')
        request = PaidBodyTargetRequest(raw, 'stat.retry', tuple(BodyTargetSelection(
            row.declaration.reference, row.target_choices[0]) for row in plan.bodies.requirements))
        g.apply(play_with_body_targets(preflight_paid_body_root_targets(g, request)))
        original = g.state.play_history[-1].body_targets
        snapshot = g.snapshot()
        branches = (g, Game.from_snapshot(snapshot, factory()), g.clone(), replay(build_replay(g), factory()))
        for branch in branches:
            self.assertEqual(branch.snapshot(), snapshot)
            pending = branch.state.pending_choice
            branch.apply(SelectChoice(pending.player_id, pending.id, ('retry',)))
            current = branch.state.play_history[-1].body_targets
            self.assertEqual(current.retry_attempt, 1); self.assertEqual(current.retry_root, original)
            target = current.selected[0].target_id
            fact = next(f for f in current.origin.entities if f.id == target)
            self.assertEqual((fact.attack, fact.max_health, fact.damage, fact.health), (1, 4, 1, 3))
            self.assertEqual(branch.state.entities[target].damage, 2)
            self.assertEqual(branch.state.players[1].mana, 4)
            self.assertIsNone(branch.state.pending_choice)
        for branch in branches:
            self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertEqual(Game.from_snapshot(g.snapshot(), factory()).snapshot(), g.snapshot())


if __name__ == '__main__':
    unittest.main()
