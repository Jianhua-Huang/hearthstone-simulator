"""Titan action policy, finite ability lifecycle, effects and player boundary."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (ActivatedAbilitySpec, Attack, CardDefinition, CardType, DamageKind,
    EndTurn, Game, IllegalAction, Keyword, MakeDormant, AwakenMinion, PlayCard, PlayerSetup,
    Registry, ResolutionError, Ruleset, Scenario, SelectChoice, SnapshotError, TargetSpec,
    TriggerSpec, UseMinionAbility, Zone)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy,
    ForceAttack, Freeze, GainArmor, GrantKeyword, RequestChoice, ReturnToHand, SetStats, Silence, Summon)
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class MinionAbilityTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=2, health=8))
        for n in range(1, 4): self.r.register_behavior(f'a{n}', lambda c, n=n: [GainArmor(c.player_id, n)])
        self.titan()
        self.spell('kill', lambda c: [Destroy(c.target_id)], requires_target=True)
        self.spell('silence', lambda c: [Silence(c.target_id)], requires_target=True)
        self.spell('wind', lambda c: [GrantKeyword(c.target_id, Keyword.WINDFURY)], requires_target=True)
        self.spell('copy', lambda c: [CopyMinion(c.target_id, 1)], requires_target=True)

    def titan(self, name='titan', abilities=None, **fields):
        defaults = dict(attack=3, health=9, keywords=(Keyword.TITAN,),
            activated_abilities=abilities or tuple(ActivatedAbilitySpec(f'a{n}', f'a{n}') for n in range(1, 4)))
        defaults.update(fields)
        self.r.register_card(CardDefinition(name, name, CardType.MINION, **defaults))

    def spell(self, name, callback, **fields):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **fields))

    def game(self, board=('titan',), hand=(), enemy=(), enemy_hand=(), deck=('plain',)*15, rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01', board=board, hand=hand, deck=deck, mana=10, max_mana=10),
            PlayerSetup('HERO_08', board=enemy, hand=enemy_hand, deck=('plain',)*15, mana=10, max_mana=10)), seed=73), self.r, ruleset=rules)

    def unit(self, g, pos=0, player=1):
        return g.state.entities[g.state.players[player].board[pos]]

    def play(self, g, name, target=None):
        p = g.state.active_player
        i = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(p, i, target))

    def use(self, g, ability, target=None, pos=0):
        return g.apply(UseMinionAbility(1, self.unit(g, pos).id, ability, target))

    def used(self, g, pos=0):
        return {a.activation.id for a in self.unit(g, pos).abilities if a.kind == 'activated' and a.consumed}

    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def check(self, g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r).snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), g.snapshot())

    def test_play_does_not_automatically_choose_ability(self):
        g = self.game(board=(), hand=('titan',)); self.play(g, 'titan')
        self.assertEqual(self.used(g), set())
        self.assertEqual(len([a for a in g.legal_actions() if isinstance(a, UseMinionAbility)]), 3)
        self.use(g, 'a2'); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2); self.check(g)

    def test_eonar_can_refresh_mana_after_spending_all_ten(self):
        g = self.game(board=(), hand=('TTN_903',)); self.play(g, 'TTN_903')
        self.assertEqual(g.state.players[1].mana, 0)
        self.use(g, 'TTN_903t3'); self.assertEqual(g.state.players[1].mana, 10)
        self.assertEqual(self.unit(g, 1).card_id, 'TTN_903t4'); self.check(g)

    def test_each_ability_once_and_one_action_per_turn(self):
        g = self.game(); self.use(g, 'a1'); before = g.snapshot()
        for ability in ('a1', 'a2', 'missing'):
            with self.assertRaises(IllegalAction): self.use(g, ability)
            self.assertEqual(g.snapshot(), before)
        self.cycle(g)
        with self.assertRaises(IllegalAction): self.use(g, 'a1')
        self.use(g, 'a2'); self.cycle(g); self.use(g, 'a3')
        self.assertEqual(self.used(g), {'a1', 'a2', 'a3'})
        with self.assertRaises(IllegalAction): g.apply(Attack(1, self.unit(g).id, g.state.players[2].hero_id))
        self.cycle(g); g.apply(Attack(1, self.unit(g).id, g.state.players[2].hero_id)); self.check(g)

    def test_unused_abilities_block_attack_even_with_charge(self):
        self.titan('charged', keywords=(Keyword.TITAN, Keyword.CHARGE))
        g = self.game(board=('charged',))
        with self.assertRaises(IllegalAction): g.apply(Attack(1, self.unit(g).id, g.state.players[2].hero_id))

    def test_windfury_shares_action_budget_and_never_reuses_ability(self):
        g = self.game(hand=('wind',)); self.play(g, 'wind', self.unit(g).id)
        self.use(g, 'a1')
        with self.assertRaises(IllegalAction): self.use(g, 'a1')
        self.use(g, 'a2')
        with self.assertRaises(IllegalAction): self.use(g, 'a3')
        self.cycle(g); self.use(g, 'a3')
        g.apply(Attack(1, self.unit(g).id, g.state.players[2].hero_id)); self.check(g)

    def test_copy_preserves_used_abilities_but_has_own_action_budget(self):
        g = self.game(hand=('copy',)); self.use(g, 'a1'); self.play(g, 'copy', self.unit(g).id)
        self.assertEqual(self.used(g, 1), {'a1'})
        self.use(g, 'a2', pos=1); self.assertEqual(self.used(g), {'a1'}); self.check(g)

    def test_exhausted_current_copy_can_attack_immediately(self):
        g = self.game(hand=('copy',))
        self.use(g, 'a1'); self.cycle(g); self.use(g, 'a2'); self.cycle(g); self.use(g, 'a3')
        self.play(g, 'copy', self.unit(g).id)
        g.apply(Attack(1, self.unit(g, 1).id, g.state.players[2].hero_id)); self.check(g)

    def test_base_copy_restarts_all_abilities(self):
        self.spell('base', lambda c: [CopyMinion(c.target_id, 1, mode='base')], requires_target=True)
        g = self.game(hand=('base',)); self.use(g, 'a1'); self.play(g, 'base', self.unit(g).id)
        self.assertEqual(self.used(g, 1), set()); self.use(g, 'a1', pos=1); self.check(g)

    def test_silence_used_titan_does_not_refund_attack(self):
        g = self.game(hand=('silence',)); self.use(g, 'a1'); self.play(g, 'silence', self.unit(g).id)
        self.assertFalse(any(a.kind == 'activated' for a in self.unit(g).abilities))
        with self.assertRaises(IllegalAction): g.apply(Attack(1, self.unit(g).id, g.state.players[2].hero_id))
        self.cycle(g); g.apply(Attack(1, self.unit(g).id, g.state.players[2].hero_id)); self.check(g)

    def test_silence_new_titan_removes_immediate_action_permission(self):
        g = self.game(board=(), hand=('titan', 'silence')); self.play(g, 'titan')
        self.play(g, 'silence', self.unit(g).id)
        with self.assertRaises(IllegalAction): self.use(g, 'a1')
        with self.assertRaises(IllegalAction): g.apply(Attack(1, self.unit(g).id, g.state.players[2].hero_id))

    def test_return_to_hand_restarts_abilities(self):
        self.spell('back', lambda c: [ReturnToHand(c.target_id)], requires_target=True)
        g = self.game(hand=('back',)); self.use(g, 'a1'); old = self.unit(g).id
        self.play(g, 'back', old); self.play(g, 'titan')
        self.assertEqual(self.unit(g).id, old); self.assertEqual(self.used(g), set())
        self.use(g, 'a1'); self.check(g)

    def test_reborn_resets_abilities_and_can_act_immediately(self):
        self.titan('reborn', keywords=(Keyword.TITAN, Keyword.REBORN))
        g = self.game(board=('reborn',), hand=('kill',)); self.use(g, 'a1')
        old = self.unit(g).id; self.play(g, 'kill', old)
        self.assertNotEqual(self.unit(g).id, old); self.assertEqual(self.unit(g).health, 1)
        self.assertEqual(self.used(g), set()); self.use(g, 'a1'); self.check(g)

    def test_dormancy_preserves_used_ability_and_attack_count(self):
        self.spell('sleep', lambda c: [MakeDormant(c.target_id, 1)], requires_target=True)
        g = self.game(hand=('sleep',)); self.use(g, 'a1'); self.play(g, 'sleep', self.unit(g).id)
        self.assertFalse(any(isinstance(a, UseMinionAbility) for a in g.legal_actions()))
        self.cycle(g); self.assertEqual(self.used(g), {'a1'}); self.use(g, 'a2'); self.check(g)

    def test_control_change_preserves_exhausted_abilities(self):
        self.spell('steal', lambda c: [ChangeControl(c.target_id, c.player_id)], requires_target=True)
        g = self.game(enemy_hand=('steal',)); self.use(g, 'a1'); i = self.unit(g).id
        g.apply(EndTurn(1)); self.play(g, 'steal', i)
        g.apply(UseMinionAbility(2, i, 'a2')); self.check(g)

    def test_frozen_titan_cannot_use_and_thaws_after_lost_action(self):
        self.spell('freeze', lambda c: [Freeze(c.target_id)], requires_target=True)
        g = self.game(hand=('freeze',)); self.play(g, 'freeze', self.unit(g).id)
        with self.assertRaises(IllegalAction): self.use(g, 'a1')
        g.apply(EndTurn(1)); self.assertFalse(self.unit(g).frozen)
        g.apply(EndTurn(2)); self.use(g, 'a1'); self.check(g)

    def test_freeze_after_used_action_persists_until_next_opportunity(self):
        self.spell('freeze', lambda c: [Freeze(c.target_id)], requires_target=True)
        g = self.game(hand=('freeze',)); self.use(g, 'a1'); self.play(g, 'freeze', self.unit(g).id)
        self.cycle(g); self.assertTrue(self.unit(g).frozen)
        self.cycle(g); self.assertFalse(self.unit(g).frozen); self.use(g, 'a2'); self.check(g)

    def targeted(self, *, kind=CardType.MINION, relation='enemy'):
        self.r.register_behavior('hit', lambda c: [Damage(c.target_id, 3, c.source_id, DamageKind.MINION_ABILITY)])
        self.titan('targeted', abilities=tuple(ActivatedAbilitySpec(f't{n}', 'hit',
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(kind,), relation=relation)) for n in range(3)))

    def test_no_target_means_no_ability_and_no_attack(self):
        self.targeted(); g = self.game(board=('targeted',))
        self.assertEqual(g.legal_ability_targets(self.unit(g).id, 't0'), ())
        self.assertFalse(any(isinstance(a, (UseMinionAbility, Attack)) for a in g.legal_actions()))
        with self.assertRaises(IllegalAction): self.use(g, 't0')

    def test_minion_targeting_ignores_elusive_and_taunt_but_not_stealth(self):
        self.targeted()
        self.r.register_card(CardDefinition('elusive', 'Elusive', CardType.MINION, health=5, keywords=(Keyword.ELUSIVE,)))
        self.r.register_card(CardDefinition('taunt', 'Taunt', CardType.MINION, health=5, keywords=(Keyword.TAUNT,)))
        self.r.register_card(CardDefinition('hidden', 'Hidden', CardType.MINION, health=5, keywords=(Keyword.STEALTH,)))
        g = self.game(board=('targeted',), enemy=('elusive', 'taunt', 'hidden'))
        targets = g.legal_ability_targets(self.unit(g).id, 't0')
        self.assertIn(self.unit(g, 0, 2).id, targets); self.assertNotIn(self.unit(g, 2, 2).id, targets)
        self.use(g, 't0', self.unit(g, 0, 2).id); self.check(g)

    def test_ability_damage_ignores_spell_damage_and_breaks_source_stealth(self):
        self.targeted()
        self.r.register_card(CardDefinition('power', 'Power', CardType.MINION, health=5, spell_damage=10))
        self.spell('hide', lambda c: [GrantKeyword(c.target_id, Keyword.STEALTH)], requires_target=True)
        g = self.game(board=('targeted', 'power'), hand=('hide',), enemy=('plain',))
        self.play(g, 'hide', self.unit(g).id); self.use(g, 't0', self.unit(g, player=2).id)
        self.assertEqual(self.unit(g, player=2).health, 5)
        self.assertNotIn(Keyword.STEALTH, self.unit(g).keywords); self.check(g)

    def test_non_damage_ability_keeps_stealth_and_is_not_attack_event(self):
        self.titan('hidden', keywords=(Keyword.TITAN, Keyword.STEALTH))
        g = self.game(board=('hidden',)); self.use(g, 'a1')
        self.assertIn(Keyword.STEALTH, self.unit(g).keywords)
        self.assertFalse(any(e.kind in ('attack_declared', 'attack_finished', 'card_played') for e in g.events)); self.check(g)

    def test_force_attack_uses_combat_without_consuming_titan_action(self):
        self.spell('force', lambda c: [ForceAttack(c.state.players[1].board[0], c.target_id)], requires_target=True)
        g = self.game(hand=('force',), enemy=('plain',))
        self.play(g, 'force', self.unit(g, player=2).id)
        self.assertEqual(self.unit(g).health, 7); self.assertEqual(self.unit(g, player=2).health, 5)
        self.assertEqual(self.unit(g).attacks_this_turn, 0); self.use(g, 'a1'); self.check(g)

    def test_frozen_titan_can_be_forced_to_fight(self):
        self.spell('force', lambda c: [Freeze(c.state.players[1].board[0]),
            ForceAttack(c.state.players[1].board[0], c.target_id)], requires_target=True)
        g = self.game(hand=('force',), enemy=('plain',)); self.play(g, 'force', self.unit(g, player=2).id)
        self.assertEqual(self.unit(g, player=2).health, 5); self.assertTrue(self.unit(g).frozen); self.check(g)

    def test_eonar_heals_and_summons_only_after_ability(self):
        self.spell('hurt', lambda c: [Damage(c.state.players[1].hero_id, 19)])
        g = self.game(board=('TTN_903',), hand=('hurt',)); self.play(g, 'hurt')
        self.use(g, 'TTN_903t2')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)
        ancient = self.unit(g, 1)
        self.assertEqual((ancient.attack, ancient.health, ancient.keywords), (5, 5, {Keyword.TAUNT}))
        kinds = [e.kind for e in g.events]
        self.assertLess(kinds.index('healed'), kinds.index('minion_ability_used'))
        self.assertLess(kinds.index('minion_ability_used'), kinds.index('minion_summoned')); self.check(g)

    def test_eonar_growth_uses_configured_hand_limit(self):
        g = self.game(board=('TTN_903',), rules=Ruleset(max_hand=5))
        self.use(g, 'TTN_903t'); self.assertEqual(len(g.state.players[1].hand), 5); self.check(g)

    def test_growth_at_full_hand_does_not_burn(self):
        g = self.game(board=('TTN_903',), hand=('plain',)*10)
        self.use(g, 'TTN_903t'); self.assertEqual(len(g.state.players[1].deck), 15)
        self.assertFalse(any(e.kind == 'card_burned' for e in g.events)); self.check(g)

    def test_growth_short_deck_has_finite_fatigue_requests(self):
        g = self.game(board=('TTN_903',), hand=('plain',)*7, deck=('plain',))
        self.use(g, 'TTN_903t'); self.assertEqual(g.state.players[1].fatigue, 2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 27); self.check(g)

    def test_eonar_full_board_still_resolves_ability(self):
        self.spell('hurt', lambda c: [Damage(c.state.players[1].hero_id, 10)])
        g = self.game(board=('TTN_903',)+('plain',)*6, hand=('hurt',))
        self.play(g, 'hurt'); self.use(g, 'TTN_903t2')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)
        self.assertEqual(len(g.state.players[1].board), 7); self.check(g)

    def test_eonar_passive_does_not_react_to_another_titan(self):
        g = self.game(board=('TTN_903', 'titan')); self.use(g, 'a1', pos=1)
        self.assertEqual(len(g.state.players[1].board), 2); self.check(g)

    def test_silenced_eonar_loses_abilities_and_passive(self):
        g = self.game(board=('TTN_903',), hand=('silence',)); self.play(g, 'silence', self.unit(g).id)
        with self.assertRaises(IllegalAction): self.use(g, 'TTN_903t3')
        self.assertEqual(len(g.state.players[1].board), 1); self.check(g)

    def test_choice_suspension_keeps_consumed_action_and_finishes_once(self):
        self.r.register_behavior('choose', lambda c: [RequestChoice(1,
            (ChoiceOption('yes', 'Yes', effects=(GainArmor(1, 4),)),), source_id=c.source_id)])
        self.titan('choice', abilities=(ActivatedAbilitySpec('choose', 'choose'),
            ActivatedAbilitySpec('a2', 'a2'), ActivatedAbilitySpec('a3', 'a3')))
        g = self.game(board=('choice',)); self.use(g, 'choose')
        self.assertEqual(self.used(g), {'choose'}); self.assertEqual(self.unit(g).attacks_this_turn, 1)
        self.assertFalse(any(e.kind == 'minion_ability_used' for e in g.events)); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), self.r)
        action = SelectChoice(1, g.state.pending_choice.id, ('yes',))
        g.apply(action); restored.apply(action)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(sum(e.kind == 'minion_ability_used' for e in g.events), 1); self.check(g)

    def test_failed_ability_rolls_back_usage_and_action(self):
        self.r.register_behavior('bad', lambda c: [Summon(1, 'missing')])
        self.titan('bad', abilities=(ActivatedAbilitySpec('bad', 'bad'),
            ActivatedAbilitySpec('a2', 'a2'), ActivatedAbilitySpec('a3', 'a3')))
        g = self.game(board=('bad',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g, 'bad')
        self.assertEqual(before, g.snapshot())

    def test_player_projection_exposes_usage_without_attachment_ids(self):
        g = self.game(); self.use(g, 'a2')
        for viewer in (1, 2):
            rows = g.observe(viewer)['players'][0]['board'][0]['minion_abilities']
            self.assertEqual(rows, [{'ability_id': f'a{n}', 'card_id': None, 'used': n == 2} for n in range(1, 4)])
        self.check(g)

    def test_player_command_uses_public_ability_key_and_rejects_opponent(self):
        g = self.game(enemy=('titan',)); port = g.for_player(1); available = port.legal_actions()
        action = next(a for a in available['actions'] if a['type'] == 'use_minion_ability' and a['ability_id'] == 'a1')
        enemy_ref = g.observe(1)['players'][1]['board'][0]['ref']; bad = dict(action, minion=enemy_ref)
        before = g.snapshot()
        self.assertFalse(port.submit({'revision': available['revision'], 'action': bad})['accepted'])
        self.assertEqual(before, g.snapshot())
        self.assertTrue(port.submit({'revision': available['revision'], 'action': action})['accepted']); self.check(g)

    def test_omniscient_ability_predicate_is_rejected_at_player_boundary(self):
        self.r.register_use_rule('private', lambda c: True)
        self.titan('private', abilities=tuple(ActivatedAbilitySpec(f'a{n}', f'a{n}', use_rule='private') for n in range(1, 4)))
        g = self.game(board=('private',))
        self.assertEqual(g.for_player(1).legal_actions()['error'], 'unsupported_rule')

    def test_action_codec_roundtrip_and_strict_fields(self):
        action = UseMinionAbility(1, 3, 'a2', 8)
        self.assertEqual(action_from_dict(action_to_dict(action)), action)
        for raw in ({'type': 'use_minion_ability', 'player_id': 1, 'entity_id': 3},
                    dict(action_to_dict(action), ability_id=True), dict(action_to_dict(action), cost=0)):
            with self.assertRaises(ValueError): action_from_dict(raw)

    def test_invalid_titan_definitions_are_rejected(self):
        for card in (CardDefinition('bad', 'Bad', CardType.MINION, health=1, keywords=(Keyword.TITAN,)),
                     replace(self.r.card('titan'), id='bad', activated_abilities=self.r.card('titan').activated_abilities[:2]),
                     replace(self.r.card('titan'), id='bad', keywords=())):
            with self.assertRaises(ValueError): self.r.register_card(card)

    def test_bare_titan_keyword_cannot_be_granted(self):
        self.spell('grant', lambda c: [GrantKeyword(c.target_id, Keyword.TITAN)], requires_target=True)
        g = self.game(board=('plain',), hand=('grant',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'grant', self.unit(g).id)
        self.assertEqual(g.snapshot(), before)

    def test_corrupt_ability_snapshot_rejected_with_recomputed_hash(self):
        g = self.game(); i = str(self.unit(g).id)
        for mutate in (lambda a: a.update(consumed='yes'), lambda a: a['activation'].update(behavior_id='missing'),
                       lambda a: a['activation'].update(card_id='plain'),
                       lambda a: a['activation'].update(targeting={'mode': 'required'})):
            with self.subTest(mutate=mutate):
                row = deepcopy(g.snapshot())
                a = next(a for a in row['state']['entities'][i]['abilities'] if a['kind'] == 'activated')
                mutate(a)
                row['state_hash'] = canonical_hash({k: v for k, v in row.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                with self.assertRaises(SnapshotError): Game.from_snapshot(row, self.r)

    def test_titans_are_excluded_from_random_inventory_without_coverage_filter(self):
        from hs_sim.engine import CardClass, CardMetadata, GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
        from hs_sim.engine.pools import resolve_candidates
        self.assertEqual(self.r.pool_card('TTN_903'), PoolCard.from_definition(self.r.card('TTN_903')))
        self.r.register_pool_card(PoolCard('unknown_titan', CardType.MINION, 8,
            CardMetadata(True, (CardClass.NEUTRAL,), None), keywords=(Keyword.TITAN,)))
        self.r.register_pool(PoolDefinition('test', 'v1', 't', 'experimental',
            tuple(PoolMember(i) for i in ('TTN_903', 'unknown_titan', 'CS2_182'))))
        rows = resolve_candidates(self.r, GenerationContext('t', 'experimental'), 'test', PoolQuery())
        self.assertEqual([r.card_id for r in rows], ['CS2_182'])

    def test_titan_descriptors_are_not_physical_cards(self):
        for card in ('TTN_903t', 'TTN_903t2', 'TTN_903t3'):
            with self.subTest(card=card), self.assertRaises((ValueError, ResolutionError)):
                self.game(hand=(card,))

    def test_real_eonar_example_restores_and_replays_through_player_api(self):
        from examples.use_titan import run
        g, snapshot = run()
        self.assertEqual(snapshot['schema_version'], 266)
        self.assertEqual(sum(e.kind == 'minion_ability_used' for e in g.events), 3)

    def test_explicit_summon_titan_has_all_abilities_available(self):
        self.spell('summon', lambda c: [Summon(1, 'titan')])
        g = self.game(board=(), hand=('summon',)); self.play(g, 'summon')
        self.use(g, 'a1'); self.check(g)

    def test_damage_ability_uses_poisonous_and_lifesteal_from_its_source(self):
        self.targeted()
        self.spell('prepare', lambda c: [Damage(c.state.players[1].hero_id, 8),
            GrantKeyword(c.target_id, Keyword.POISONOUS), GrantKeyword(c.target_id, Keyword.LIFESTEAL)], requires_target=True)
        g = self.game(board=('targeted',), hand=('prepare',), enemy=('plain',))
        self.play(g, 'prepare', self.unit(g).id); self.use(g, 't0', self.unit(g, player=2).id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 25)
        self.assertFalse(g.state.players[2].board); self.check(g)

    def test_prevented_damage_ability_keeps_stealth(self):
        self.targeted()
        self.r.register_card(CardDefinition('shield', 'Shield', CardType.MINION, health=3, keywords=(Keyword.DIVINE_SHIELD,)))
        self.spell('hide', lambda c: [GrantKeyword(c.target_id, Keyword.STEALTH)], requires_target=True)
        g = self.game(board=('targeted',), hand=('hide',), enemy=('shield',))
        self.play(g, 'hide', self.unit(g).id); self.use(g, 't0', self.unit(g, player=2).id)
        self.assertIn(Keyword.STEALTH, self.unit(g).keywords); self.check(g)

    def test_dormant_enemy_is_not_a_minion_ability_target(self):
        self.targeted(); g = self.game(board=('targeted',), enemy=('BT_004',))
        self.assertEqual(g.legal_ability_targets(self.unit(g).id, 't0'), ())

    def test_player_visible_use_rule_matches_enumeration_and_submission(self):
        self.r.register_use_rule('armor_needed', lambda c: c.observation['players'][0]['hero']['armor'] == 0, visibility='player')
        self.titan('conditional', abilities=tuple(ActivatedAbilitySpec(f'a{n}', f'a{n}', use_rule='armor_needed') for n in range(1, 4)))
        g = self.game(board=('conditional',)); self.use(g, 'a1'); self.cycle(g)
        self.assertFalse(any(a['type'] == 'use_minion_ability' for a in g.for_player(1).legal_actions()['actions']))
        with self.assertRaises(IllegalAction): self.use(g, 'a2')

    def test_enemy_hidden_cards_do_not_change_player_ability_actions(self):
        a = self.game(enemy_hand=('plain',)); b = self.game(enemy_hand=('TTN_903',))
        self.assertEqual(a.for_player(1).legal_actions(), b.for_player(1).legal_actions())

    def test_dead_eonar_does_not_summon_ancient_after_completion(self):
        self.r.register_behavior('kill_source', lambda c: [Destroy(c.event.source_id)])
        self.r.register_card(CardDefinition('watch', 'Watch', CardType.MINION, health=1,
            triggers=(TriggerSpec('minion_ability_started', 'kill_source'),)))
        g = self.game(board=('TTN_903', 'watch'))
        self.use(g, 'TTN_903t3')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], ['watch']); self.check(g)

    def test_eonar_passive_cannot_be_reenabled_by_another_ability_after_silence(self):
        self.r.register_behavior('silence_source', lambda c: [Silence(c.event.source_id)])
        self.r.register_card(CardDefinition('watch', 'Watch', CardType.MINION, health=1,
            triggers=(TriggerSpec('minion_ability_started', 'silence_source'),)))
        g = self.game(board=('TTN_903', 'watch')); self.use(g, 'TTN_903t3')
        self.assertTrue(self.unit(g).silenced); self.assertEqual(len(g.state.players[1].board), 2); self.check(g)

    def test_minion_ability_damage_rejects_wrong_source_type(self):
        self.spell('invalid_damage', lambda c: [Damage(c.state.players[2].hero_id, 1, c.source_id, DamageKind.MINION_ABILITY)])
        g = self.game(hand=('invalid_damage',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'invalid_damage')
        self.assertEqual(g.snapshot(), before)

    def test_force_attack_skips_departed_target_without_using_ability(self):
        self.spell('force_dead', lambda c: [Destroy(c.target_id), ForceAttack(c.state.players[1].board[0], c.target_id)], requires_target=True)
        g = self.game(hand=('force_dead',), enemy=('plain',))
        self.play(g, 'force_dead', self.unit(g, player=2).id)
        self.assertEqual(self.unit(g).attacks_this_turn, 0); self.use(g, 'a1'); self.check(g)

    def test_unknown_ability_behavior_fails_registry_validation(self):
        self.titan('missing_behavior', abilities=(ActivatedAbilitySpec('bad', 'missing'),
            ActivatedAbilitySpec('a2', 'a2'), ActivatedAbilitySpec('a3', 'a3')))
        with self.assertRaises(ValueError): self.r.validate()

    def test_public_log_keeps_chosen_ability_when_source_dies(self):
        self.r.register_behavior('kill_source', lambda c: [Destroy(c.event.source_id)])
        self.r.register_card(CardDefinition('watch', 'Watch', CardType.MINION, health=1,
            triggers=(TriggerSpec('minion_ability_started', 'kill_source'),)))
        g = self.game(board=('TTN_903', 'watch')); self.use(g, 'TTN_903t3')
        for viewer in (1, 2):
            events = [e for e in g.player_events(viewer) if e['kind'] == 'minion_ability_used']
            self.assertEqual(events[0]['minion_ability'], {'ability_id': 'TTN_903t3', 'card_id': 'TTN_903t3'})
        self.check(g)

    def test_public_ability_log_rejects_physical_card_in_descriptor_field(self):
        g = self.game(); self.use(g, 'a1'); row = g.snapshot()
        for player in row['information']['players'].values():
            for event in player['events']:
                if event['kind'] == 'minion_ability_used': event['minion_ability']['card_id'] = 'plain'
        row['state_hash'] = canonical_hash({k: v for k, v in row.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(row, self.r)


if __name__ == '__main__':
    unittest.main()
