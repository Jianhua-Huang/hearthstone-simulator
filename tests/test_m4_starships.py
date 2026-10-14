"""Starship construction and launch across death, lifecycle and player boundaries."""
from hs_sim.engine.model import CostAuraSpec
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (Attack, AuraSpec, CardClass, CardDefinition, CardMetadata, CardType,
    CostSpec, Game, IllegalAction, Keyword, LaunchStarship, LaunchStarshipEffect, PlayCard,
    PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import (AddCostModifier, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, DamageBatch, Destroy, Draw, Freeze, GainArmor, GrantDeathrattle, GrantKeyword,
    Heal, ModifyCost, RandomDamage, RequestChoice, ReturnToHand, SetStats, ShuffleIntoDeck,
    Silence, Summon, Transform)
from hs_sim.engine.model import DamageKind, HealthFlow, HealthOp, HealthRule
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.starships import construction
from hs_sim.engine.zones import CardReference, CopyCard


class StarshipTests(unittest.TestCase):
    def setUp(self):
        self.r = Registry('starship-tests-v1')
        self.r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        self.r.register_card(CardDefinition('ship', 'ship', CardType.MINION, cost=5,
                                            starship_for=(CardClass.NEUTRAL,)))
        self.r.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=1, health=20))
        self.r.register_behavior('armor', lambda c: [GainArmor(c.player_id, 4)])
        self.r.register_card(CardDefinition('piece', 'piece', CardType.MINION, attack=3, health=4,
            keywords=(Keyword.STARSHIP_PIECE, Keyword.TAUNT), deathrattle='armor'))
        self.r.register_card(CardDefinition('shield', 'shield', CardType.MINION, attack=2, health=2,
            keywords=(Keyword.STARSHIP_PIECE, Keyword.DIVINE_SHIELD)))
        self.spell('kill', lambda c: [Destroy(c.state.players[c.player_id].board[0])])
        self.spell('all', lambda c: [DamageBatch(tuple(Damage(i, 100) for p in c.state.players.values() for i in p.board))])

    def spell(self, name, callback, **kwargs):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kwargs))

    def variant(self, name, **kwargs):
        self.r.register_card(replace(self.r.card(kwargs.pop('base', 'piece')), id=name, **kwargs))

    def game(self, board=('piece',), hand=('kill',), enemy=(), enemy_hand=(), mana=10, seed=19, hero='hero'):
        return Game.from_scenario(Scenario((PlayerSetup(hero, board=board, hand=hand, max_mana=10, mana=mana),
            PlayerSetup('hero', board=enemy, hand=enemy_hand)), seed=seed), self.r)

    def cast(self, g, name):
        i = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, i))

    def ship(self, g, player=1):
        return construction(g.state, player)

    def launch(self, g):
        i = self.ship(g).id
        g.apply(LaunchStarship(1, i))
        return g.state.entities[i]

    def check_replay(self, g):
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), g.snapshot())

    def test_death_starts_inactive_construction_without_summon(self):
        g = self.game(); result = self.cast(g, 'kill'); ship = self.ship(g)
        self.assertEqual((ship.attack, ship.health, ship.components), (3, 4, ('piece',)))
        self.assertFalse(ship.active); self.assertFalse(ship.keywords)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 4)
        self.assertFalse(any(e.kind == 'minion_summoned' for e in result.events))
        self.assertEqual(len(g.state.death_history), 1)
        self.check_replay(g)

    def test_same_batch_duplicate_parts_keep_independent_deathrattles(self):
        g = self.game(board=('piece', 'piece'), hand=('all', 'all'))
        self.cast(g, 'all'); ship = self.ship(g)
        self.assertEqual((ship.attack, ship.health, ship.components), (6, 8, ('piece', 'piece')))
        self.assertEqual(len(g.state.players[1].board), 1)
        self.assertEqual(len({d.batch for d in g.state.death_history}), 1)
        self.launch(g); self.cast(g, 'all')
        self.assertIsNone(self.ship(g))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 16)
        self.check_replay(g)

    def test_printed_stats_and_keywords_ignore_buffs_and_consumption(self):
        self.spell('prepare', lambda c: [Buff(c.state.players[1].board[0], 10, 10),
            GrantKeyword(c.state.players[1].board[0], Keyword.LIFESTEAL),
            GrantDeathrattle(c.state.players[1].board[0], 'armor'),
            Damage(c.state.players[1].board[0], 1), Destroy(c.state.players[1].board[0])])
        g = self.game(board=('shield',), hand=('prepare',))
        self.cast(g, 'prepare'); s = self.launch(g)
        self.assertEqual((s.attack, s.health), (2, 2))
        self.assertEqual(s.keywords, {Keyword.DIVINE_SHIELD})
        self.assertFalse(any(a.kind == 'deathrattle' for a in s.abilities))

    def test_silenced_piece_does_not_contribute(self):
        self.spell('silencekill', lambda c: [Silence(c.state.players[1].board[0]), Destroy(c.state.players[1].board[0])])
        g = self.game(hand=('silencekill',)); self.cast(g, 'silencekill')
        self.assertIsNone(self.ship(g))

    def test_transformed_piece_does_not_contribute(self):
        self.spell('transformkill', lambda c: [Transform(c.state.players[1].board[0], 'plain'), Destroy(c.state.players[1].board[0])])
        g = self.game(hand=('transformkill',)); self.cast(g, 'transformkill')
        self.assertIsNone(self.ship(g))

    def test_non_death_departure_does_not_contribute(self):
        self.spell('bounce', lambda c: [ReturnToHand(c.state.players[1].board[0])])
        g = self.game(hand=('bounce',)); self.cast(g, 'bounce')
        self.assertIsNone(self.ship(g)); self.assertFalse(g.state.death_history)

    def test_death_controller_receives_contribution(self):
        self.spell('steal', lambda c: [ChangeControl(c.state.players[2].board[0], 1)])
        g = self.game(board=(), enemy=('piece',), hand=('steal', 'kill'))
        self.cast(g, 'steal'); self.cast(g, 'kill')
        self.assertIsNotNone(self.ship(g)); self.assertIsNone(self.ship(g, 2))
        self.assertEqual(g.state.death_history[0].owner, 2)

    def test_two_players_build_independently_in_same_batch(self):
        g = self.game(enemy=('piece',), hand=('all',)); self.cast(g, 'all')
        self.assertEqual(self.ship(g).components, ('piece',))
        self.assertEqual(self.ship(g, 2).components, ('piece',))
        self.assertNotEqual(self.ship(g).id, self.ship(g, 2).id)

    def test_reborn_piece_adds_again_when_it_dies_again(self):
        self.variant('reborn', keywords=(Keyword.STARSHIP_PIECE, Keyword.REBORN))
        g = self.game(board=('reborn',), hand=('all', 'all'))
        self.cast(g, 'all'); self.cast(g, 'all')
        self.assertEqual(self.ship(g).components, ('reborn', 'reborn'))
        self.check_replay(g)

    def test_full_board_reserves_slot_and_launches_in_place(self):
        self.spell('summon', lambda c: [Summon(1, 'plain')])
        g = self.game(board=('piece',) + ('plain',) * 6, hand=('kill', 'summon', 'plain'))
        self.cast(g, 'kill'); ship = self.ship(g)
        self.assertEqual(len(g.state.players[1].board), 7)
        result = self.cast(g, 'summon')
        self.assertTrue(any(e.kind == 'summon_failed' for e in result.events))
        self.assertFalse(any(isinstance(a, PlayCard) for a in g.legal_actions()))
        launched = self.launch(g)
        self.assertEqual(launched.id, ship.id)
        self.assertEqual(len(g.state.players[1].board), 7)

    def test_launch_cost_is_independent_of_minion_discount(self):
        self.spell('discount', lambda c: [AddCostModifier(1, CostSpec(delta=-5, card_types=(CardType.MINION,)), 1)])
        g = self.game(hand=('discount', 'kill')); self.cast(g, 'discount'); self.cast(g, 'kill')
        self.launch(g)
        self.assertEqual(g.state.players[1].mana, 5)
        self.assertEqual(len(g.state.players[1].cost_modifiers), 1)

    def test_insufficient_mana_launch_does_not_mutate(self):
        g = self.game(mana=4); self.cast(g, 'kill'); before = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(LaunchStarship(1, self.ship(g).id))
        self.assertEqual(before, g.snapshot())
        self.assertFalse(any(isinstance(a, LaunchStarship) for a in g.legal_actions()))

    def test_free_effect_launches_without_mana(self):
        self.spell('free', lambda c: [LaunchStarshipEffect(1, construction(c.state, 1).id)])
        g = self.game(mana=0, hand=('kill', 'free')); self.cast(g, 'kill'); i = self.ship(g).id
        self.cast(g, 'free'); self.assertTrue(g.state.entities[i].active)
        self.assertEqual(g.state.players[1].mana, 0)

    def test_next_piece_starts_new_ship_without_changing_launched_one(self):
        self.spell('extra', lambda c: [Summon(1, 'piece')])
        self.spell('killlast', lambda c: [Destroy(c.state.players[1].board[-1])])
        g = self.game(hand=('kill', 'extra', 'killlast'))
        self.cast(g, 'kill'); old = self.launch(g)
        self.cast(g, 'extra'); self.cast(g, 'killlast'); new = self.ship(g)
        self.assertNotEqual(old.id, new.id)
        self.assertEqual(g.state.entities[old.id].components, ('piece',))
        self.assertEqual(new.components, ('piece',))

    def test_inactive_ship_cannot_attack_be_attacked_or_supply_taunt(self):
        g = self.game(enemy=('plain',)); self.cast(g, 'kill'); s = self.ship(g)
        enemy = g.state.players[2].board[0]
        with self.assertRaises(IllegalAction): g.validate(Attack(1, s.id, enemy))
        from hs_sim.engine.combat import attack_error
        state = g.state; state.entities[enemy].summoned_turn = 0
        self.assertIsNotNone(attack_error(state, enemy, s.id, 2))
        self.assertIsNone(attack_error(state, enemy, state.players[1].hero_id, 2))

    def test_launch_resets_summoning_turn_and_activates_taunt(self):
        g = self.game(enemy=('plain',)); self.cast(g, 'kill'); s = self.launch(g)
        with self.assertRaises(IllegalAction): g.validate(Attack(1, s.id, g.state.players[2].hero_id))
        from hs_sim.engine.combat import attack_error
        state = g.state; enemy = state.players[2].board[0]; state.entities[enemy].summoned_turn = 0
        self.assertIsNotNone(attack_error(state, enemy, state.players[1].hero_id, 2))
        self.assertIsNone(attack_error(state, enemy, s.id, 2))

    def test_rush_component_allows_launch_turn_minion_attack(self):
        self.variant('rush', keywords=(Keyword.STARSHIP_PIECE, Keyword.RUSH))
        g = self.game(board=('rush',), enemy=('plain',)); self.cast(g, 'kill'); s = self.launch(g)
        g.validate(Attack(1, s.id, g.state.players[2].board[0]))
        with self.assertRaises(IllegalAction): g.validate(Attack(1, s.id, g.state.players[2].hero_id))

    def test_targeted_spell_rejects_inactive_board_entity(self):
        self.spell('target', lambda c: [Damage(c.target_id, 1)], requires_target=True, target_rule='any_character')
        g = self.game(hand=('kill', 'target')); self.cast(g, 'kill'); i = g.state.players[1].hand[0]
        self.assertNotIn(self.ship(g).id, g.legal_targets(i))
        with self.assertRaises(IllegalAction): g.apply(PlayCard(1, i, self.ship(g).id))

    def test_ordinary_effects_ignore_construction(self):
        def affect(c):
            i = construction(c.state, 1).id
            return [Damage(i, 100), Destroy(i), Buff(i, 9, 9), SetStats(i, attack=1, health=1),
                Freeze(i), Heal(i, 10), Silence(i), GrantKeyword(i, Keyword.CHARGE),
                ModifyCost(i, CostSpec(delta=-1)), ReturnToHand(i), ShuffleIntoDeck(i),
                Transform(i, 'plain'), ChangeControl(i, 2), CopyMinion(i, 2)]
        self.spell('affect', affect)
        g = self.game(hand=('kill', 'affect')); self.cast(g, 'kill'); before = self.ship(g)
        self.cast(g, 'affect'); self.assertEqual(before, self.ship(g))
        self.assertFalse(g.state.players[2].board)

    def test_random_damage_excludes_construction_from_candidates(self):
        self.spell('random', lambda c: [RandomDamage(tuple(c.state.players[1].board), 5)])
        g = self.game(board=('piece', 'plain'), hand=('kill', 'random')); self.cast(g, 'kill')
        self.cast(g, 'random'); self.assertEqual(self.ship(g).health, 4)
        plain = next(e for e in g.state.entities.values() if e.card_id == 'plain')
        self.assertEqual(plain.damage, 5)

    def test_aura_does_not_apply_to_or_from_construction(self):
        self.variant('aura', auras=(AuraSpec(attack=2, health=3),))
        self.variant('support', base='plain', auras=(AuraSpec(attack=5, health=6),))
        g = self.game(board=('aura', 'support')); self.cast(g, 'kill')
        self.assertEqual((self.ship(g).attack, self.ship(g).health), (3, 4))
        support = next(g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == 'support')
        self.assertEqual(support.attack, 1)
        self.launch(g)
        support = g.state.entities[support.id]
        self.assertEqual((support.attack, support.health), (3, 23))

    def test_inactive_spell_damage_cost_aura_and_packet_rules(self):
        self.variant('caster', deathrattle=None, spell_damage=5, cost_auras=(CostAuraSpec(CostSpec(delta=-2)),),
            health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.ADD, amount=2, source_relation='friendly'),))
        self.spell('bolt', lambda c: [Damage(c.state.players[2].hero_id, 1, c.source_id, DamageKind.SPELL)], cost=2)
        g = self.game(board=('caster',), hand=('kill', 'bolt', 'bolt')); self.cast(g, 'kill')
        first = g.state.players[1].hand[0]; self.assertEqual(g.quote_cost(first).amount, 2)
        self.cast(g, 'bolt'); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 29)
        self.launch(g); self.assertEqual(g.quote_cost(g.state.players[1].hand[0]).amount, 0)
        self.cast(g, 'bolt'); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 21)

    def test_inactive_event_trigger_activates_only_after_launch(self):
        self.variant('watch', deathrattle=None, triggers=(TriggerSpec('card_played', 'armor'),))
        self.spell('nothing', lambda c: [])
        g = self.game(board=('watch',), hand=('kill', 'nothing', 'nothing')); self.cast(g, 'kill')
        self.cast(g, 'nothing'); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.launch(g); self.cast(g, 'nothing')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 4)

    def test_bounce_and_replay_preserve_composed_base(self):
        self.spell('bounce', lambda c: [Buff(c.state.players[1].board[0], 8, 8), ReturnToHand(c.state.players[1].board[0])])
        g = self.game(hand=('kill', 'bounce')); self.cast(g, 'kill'); old = self.launch(g)
        self.cast(g, 'bounce'); s = g.state.entities[old.id]
        self.assertEqual((s.zone, s.attack, s.health, s.components), (Zone.HAND, 3, 4, ('piece',)))
        g.apply(PlayCard(1, s.id)); self.assertFalse(g.state.entities[s.id].starship_building)
        self.check_replay(g)

    def test_silence_keeps_composed_stats_but_removes_effects(self):
        self.spell('silence', lambda c: [Silence(c.state.players[1].board[0])])
        g = self.game(hand=('kill', 'silence')); self.cast(g, 'kill'); old = self.launch(g)
        self.cast(g, 'silence'); s = g.state.entities[old.id]
        self.assertEqual((s.attack, s.health, s.components), (3, 4, ('piece',)))
        self.assertFalse(s.keywords); self.assertFalse(s.abilities)

    def test_copy_modes_and_shuffle_preserve_composition(self):
        self.spell('copies', lambda c: [Buff(c.state.players[1].board[0], 2, 2),
            CopyMinion(c.state.players[1].board[0], 1), CopyMinion(c.state.players[1].board[0], 1, mode='base'),
            ShuffleIntoDeck(c.state.players[1].board[0])])
        g = self.game(hand=('kill', 'copies')); self.cast(g, 'kill'); old = self.launch(g)
        self.cast(g, 'copies'); board = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([s.attack for s in board], [5, 3])
        self.assertTrue(all(s.components == ('piece',) for s in board))
        self.assertEqual(g.state.entities[old.id].attack, 3)
        self.check_replay(g)

    def test_hand_copy_preserves_composite_base(self):
        self.spell('bounce', lambda c: [ReturnToHand(c.state.players[1].board[0])])
        self.spell('copyhand', lambda c: [CopyCard(CardReference.capture(c.state.entities[c.state.players[1].hand[-1]]), 1, mode='base')])
        g = self.game(hand=('kill', 'bounce', 'copyhand')); self.cast(g, 'kill'); self.launch(g)
        self.cast(g, 'bounce'); self.cast(g, 'copyhand')
        self.assertEqual([g.state.entities[i].components for i in g.state.players[1].hand], [('piece',), ('piece',)])
        self.check_replay(g)

    def test_transform_discards_composition(self):
        self.spell('transform', lambda c: [Transform(c.state.players[1].board[0], 'plain')])
        g = self.game(hand=('kill', 'transform')); self.cast(g, 'kill'); old = self.launch(g)
        self.cast(g, 'transform'); s = g.state.entities[old.id]
        self.assertEqual((s.card_id, s.components, s.attack), ('plain', (), 1))
        self.check_replay(g)

    def test_reborn_starship_uses_death_composition(self):
        self.spell('rebornkill', lambda c: [GrantKeyword(c.state.players[1].board[0], Keyword.REBORN), Destroy(c.state.players[1].board[0])])
        g = self.game(hand=('kill', 'rebornkill')); self.cast(g, 'kill'); old = self.launch(g)
        self.cast(g, 'rebornkill'); s = g.state.entities[g.state.players[1].board[0]]
        self.assertNotEqual(old.id, s.id); self.assertEqual(s.health, 1)
        self.assertEqual(s.components, ('piece',)); self.assertEqual(s.attack, 3)
        self.check_replay(g)

    def test_class_body_selection_and_neutral_fallback(self):
        self.r.register_card(CardDefinition('hunter', 'hunter', CardType.HERO, health=30,
            metadata=CardMetadata(False, (CardClass.HUNTER,), None)))
        self.r.register_card(CardDefinition('hunter_ship', 'hunter_ship', CardType.MINION, cost=5,
            starship_for=(CardClass.HUNTER,)))
        g = self.game(hero='hunter'); self.cast(g, 'kill'); self.assertEqual(self.ship(g).card_id, 'hunter_ship')
        neutral = self.game(); self.cast(neutral, 'kill'); self.assertEqual(self.ship(neutral).card_id, 'ship')

    def test_launch_effects_execute_each_duplicate_and_do_not_run_battlecry(self):
        self.r.register_behavior('battlecry', lambda c: [GainArmor(c.player_id, 99)])
        self.variant('launch_piece', deathrattle=None, on_launch='armor', on_play='battlecry')
        g = self.game(board=('launch_piece', 'launch_piece'), hand=('all',)); self.cast(g, 'all')
        self.launch(g); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 8)
        self.check_replay(g)

    def test_launch_choice_pauses_and_restores_remaining_work(self):
        self.r.register_behavior('choose', lambda c: [RequestChoice(1, (
            ChoiceOption('yes', 'yes', (GainArmor(1, 7),)),), source_id=c.source_id), GainArmor(1, 2)])
        self.variant('choice_piece', on_launch='choose', deathrattle=None)
        g = self.game(board=('choice_piece', 'choice_piece'), hand=('all',)); self.cast(g, 'all'); self.launch(g)
        self.assertIsNotNone(g.state.pending_choice)
        clone = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r)
        while g.state.pending_choice:
            c = g.state.pending_choice; action = SelectChoice(c.player_id, c.id, ('yes',))
            g.apply(action); clone.apply(action)
        self.assertEqual(clone.snapshot(), g.snapshot())
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 18)
        self.check_replay(g)

    def test_launch_order_is_seeded_shuffle_not_timestamp(self):
        for n in range(4):
            self.r.register_behavior(f'launch{n}', lambda c, n=n: [GainArmor(c.player_id, n+1)])
            self.variant(f'p{n}', on_launch=f'launch{n}', deathrattle=None)
        orders = set()
        for seed in range(5):
            g = self.game(board=tuple(f'p{n}' for n in range(4)), hand=('all',), seed=seed)
            self.cast(g, 'all'); clone = g.clone(); i = self.ship(g).id
            result = g.apply(LaunchStarship(1, i)); clone.apply(LaunchStarship(1, i))
            orders.add(tuple(e.amount for e in result.events if e.kind == 'armor_gained'))
            self.assertEqual(clone.snapshot(), g.snapshot()); self.check_replay(g)
        self.assertGreater(len(orders), 1)

    def test_player_views_and_commands_expose_only_public_starship_data(self):
        g = self.game(); self.cast(g, 'kill')
        for viewer in (1, 2):
            view = g.observe(viewer)['players'][0]['board'][0]
            self.assertEqual(view['starship'], {'building': True, 'components': ['piece'], 'launch_cost': 5})
            self.assertNotIn('id', view)
        port = g.for_player(1); commands = port.legal_actions()
        command = next(a for a in commands['actions'] if a['type'] == 'launch_starship')
        result = port.submit({'revision': commands['revision'], 'action': command})
        self.assertTrue(result['accepted']); self.assertIsNone(self.ship(g)); self.check_replay(g)

    def test_player_cannot_launch_enemy_construction(self):
        g = self.game(board=(), enemy=('piece',), hand=('all',)); self.cast(g, 'all')
        port = g.for_player(1); view = port.observe(); before = g.snapshot()
        enemy = view['observation']['players'][1]['board'][0]['ref']
        response = port.submit({'revision': view['revision'], 'action': {'type': 'launch_starship', 'starship': enemy}})
        self.assertFalse(response['accepted']); self.assertEqual(g.snapshot(), before)

    def test_strict_action_and_snapshot_fields(self):
        a = LaunchStarship(1, 3); self.assertEqual(action_from_dict(action_to_dict(a)), a)
        for changes in ({'entity_id': True}, {'player_id': 3}, {'cost': 0}, {'target_id': 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): action_from_dict({**action_to_dict(a), **changes})
        g = self.game(); self.cast(g, 'kill'); i = str(self.ship(g).id)
        for changes in ({'components': []}, {'components': ['absent']}, {'components': ['ship']},
                        {'components': ['plain']}, {'components': 'piece'}, {'starship_building': 1},
                        {'base_attack': 7}, {'damage': 1}, {'silenced': True}):
            snapshot = g.snapshot(); snapshot['state']['entities'][i].update(changes)
            with self.subTest(changes=changes), self.assertRaises(SnapshotError): Game.from_snapshot(snapshot, self.r)
        for old in range(1, 28):
            snapshot = g.snapshot(); snapshot['schema_version'] = old
            with self.subTest(schema=old), self.assertRaises(SnapshotError): Game.from_snapshot(snapshot, self.r)

    def test_bare_starship_body_cannot_be_summoned(self):
        self.spell('bare', lambda c: [Summon(1, 'ship')])
        g = self.game(board=(), hand=('bare',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'bare')
        self.assertEqual(g.snapshot(), before)

    def test_failure_after_launch_rolls_back_rng_payment_and_construction(self):
        self.r.register_behavior('fail', lambda c: [Summon(c.player_id, 'absent')])
        self.variant('badpiece', on_launch='fail')
        g = self.game(board=('badpiece',), hand=('kill',)); self.cast(g, 'kill'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.launch(g)
        self.assertEqual(before, g.snapshot())

    def test_real_card_example_restores_launch_and_composite_death(self):
        from examples.build_starship import run
        g, snapshot = run()
        self.assertEqual(len(g.history), 12)
        ship = next(e for e in g.state.entities.values() if e.components)
        self.assertEqual(ship.card_id, 'GDB_100t2')
        self.assertEqual(ship.components, ('GDB_111', 'GDB_109', 'GDB_100', 'GDB_101'))
        self.assertEqual(ship.zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.death_history[-1].attack, 10)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 7)
        self.assertTrue(snapshot['state']['entities'][str(ship.id)]['starship_building'])

    def test_class_body_templates_and_component_adapters_are_pinned(self):
        from hs_sim.engine.representative import build_registry
        r = build_registry()
        for card_id, cls in (('GDB_100t2', CardClass.NEUTRAL), ('GDB_100t4', CardClass.DEATH_KNIGHT),
                            ('GDB_100t5', CardClass.DEMON_HUNTER), ('GDB_100t6', CardClass.DRUID),
                            ('GDB_100t7', CardClass.HUNTER), ('GDB_100t8', CardClass.ROGUE),
                            ('GDB_100t9', CardClass.WARLOCK)):
            self.assertEqual(r.card(card_id).starship_for, (cls,))
        self.assertEqual((r.card('GDB_100').attack, r.card('GDB_100').health), (3, 4))
        self.assertIn(Keyword.DIVINE_SHIELD, r.card('GDB_101').keywords)
        self.assertIn(Keyword.LIFESTEAL, r.card('GDB_109').keywords)
        self.assertEqual(r.card('SC_999t').starship_for, (CardClass.PALADIN, CardClass.SHAMAN, CardClass.WARRIOR))
        self.assertEqual(r.card('SC_999t').metadata.tribes, ('mech',))

    def test_current_warrior_uses_battlecruiser_instead_of_neutral_body(self):
        from hs_sim.engine.representative import build_registry
        r = build_registry()
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_01', board=('GDB_100',),
                hand=('CS2_029',), max_mana=10, mana=10), PlayerSetup('HERO_08'))), r)
        g.apply(PlayCard(1, g.state.players[1].hand[0], g.state.players[1].board[0]))
        self.assertEqual(construction(g.state, 1).card_id, 'SC_999t')

    def test_missing_body_definition_rolls_back_piece_death(self):
        r = Registry('no-body')
        for card in (self.r.card('hero'), self.r.card('piece'), self.r.card('kill')): r.register_card(card)
        r.register_behavior('armor', lambda c: [])
        r.register_behavior('kill', lambda c: [Destroy(c.state.players[1].board[0])])
        g = Game.from_scenario(Scenario((PlayerSetup('hero', board=('piece',), hand=('kill',)), PlayerSetup('hero'))), r)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'kill')
        self.assertEqual(g.snapshot(), before)

    def test_registration_rejects_ambiguous_or_invalid_bodies(self):
        for changed in ({'health': 1}, {'starship_for': ('mage',)}, {'keywords': (Keyword.STARSHIP_PIECE,)},
                        {'starship_for': (CardClass.NEUTRAL, CardClass.NEUTRAL)}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.r.register_card(replace(self.r.card('ship'), id='bad', **changed))
        self.r.register_card(replace(self.r.card('ship'), id='duplicate'))
        with self.assertRaises(ValueError): self.r.freeze()

    def test_deathrattle_summon_observes_reserved_construction_slot(self):
        self.r.register_behavior('summon', lambda c: [Summon(c.player_id, 'plain')])
        self.variant('summoner', deathrattle='summon')
        g = self.game(board=('summoner',) + ('plain',)*6)
        result = self.cast(g, 'kill')
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertIsNotNone(self.ship(g))
        self.assertTrue(any(e.kind == 'summon_failed' for e in result.events))

    def test_launched_ship_given_piece_keyword_contributes_composed_base(self):
        self.spell('recycle', lambda c: [GrantKeyword(c.state.players[1].board[0], Keyword.STARSHIP_PIECE),
                                       Destroy(c.state.players[1].board[0])])
        g = self.game(hand=('kill', 'recycle')); self.cast(g, 'kill'); old = self.launch(g)
        self.cast(g, 'recycle'); new = self.ship(g)
        self.assertNotEqual(new.id, old.id); self.assertEqual(new.components, old.components)
        self.check_replay(g)

    def test_stale_free_launch_does_not_activate_subsequent_construction(self):
        self.spell('next', lambda c: [Summon(1, 'piece')])
        self.spell('killlast', lambda c: [Destroy(c.state.players[1].board[-1])])
        self.spell('stale', lambda c: [LaunchStarshipEffect(1, c.state.players[1].board[0])])
        g = self.game(hand=('kill', 'next', 'killlast', 'stale')); self.cast(g, 'kill'); self.launch(g)
        self.cast(g, 'next'); self.cast(g, 'killlast'); before = self.ship(g)
        self.cast(g, 'stale'); self.assertEqual(self.ship(g), before)


if __name__ == '__main__':
    unittest.main()
