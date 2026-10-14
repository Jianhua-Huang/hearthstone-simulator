"""Actual Adapt recipes over the existing choices and attachment interpreter."""
import json
import random
import unittest
from dataclasses import replace

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, Scenario, SelectChoice,
    SpellSchool, Zone)
from hs_sim.engine.adapt import (CHOICE_IDS, PLANT_ID, SPORES_BEHAVIOR, VERSION,
    adapt, records, register_adapt_options)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (CopyMinion, Damage, Destroy, GainArmor,
    RandomDamage, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import rng_from_json

SELF, DOUBLE, GROUP = 'UNG_001', 'UNG_002', 'UNG_103'
ATTACK, HEALTH, STATS = 'UNG_999t3', 'UNG_999t4', 'UNG_999t14'
SHIELD, STEALTH, SPORES = 'UNG_999t8', 'UNG_999t10', 'UNG_999t2'


def seed_for(*rounds):
    for seed in range(1000):
        rng = random.Random(seed)
        if all(cid in rng.sample(CHOICE_IDS, 3) for cid in rounds):
            return seed
    raise AssertionError('No fixture seed')


def registry(extras=(), omitted=None):
    r = Registry('adapt-basics-' + VERSION)
    register_adapt_options(r)
    if omitted is not None:
        r._cards.pop(omitted)
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=40))
    for cid in ('body', 'left', 'right'):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=2, health=5))
    r.register_card(CardDefinition('shielded', 'shielded', CardType.MINION,
        attack=2, health=5, keywords=(Keyword.DIVINE_SHIELD, Keyword.WINDFURY, Keyword.TAUNT)))
    r.register_behavior('adapt.self', lambda c: adapt(c, (c.source_id,), r))
    r.register_behavior('adapt.twice', lambda c: (*adapt(c, (c.source_id,), r),
                                                *adapt(c, (c.source_id,), r)))
    r.register_behavior('adapt.group', lambda c: adapt(c, tuple(c.state.players[c.player_id].board), r))
    raw = records()
    for cid, behavior in ((SELF, 'adapt.self'), (DOUBLE, 'adapt.twice'), (GROUP, 'adapt.group')):
        row, tags = raw[cid], raw[cid]['tags']
        meta = CardMetadata(True, (CardClass.DRUID if cid == GROUP else CardClass.NEUTRAL,),
                            Rarity.COMMON if tags['RARITY'] == 1 else Rarity.RARE,
                            tribes=() if cid == GROUP else ('beast',))
        r.register_card(CardDefinition(cid, row['name'], CardType.SPELL if cid == GROUP else CardType.MINION,
            cost=tags.get('COST', 0), attack=tags.get('ATK', 0), health=tags.get('HEALTH', 0),
            battlecry=None if cid == GROUP else behavior, on_play=behavior if cid == GROUP else None,
            spell_school=SpellSchool.NATURE if cid == GROUP else None, metadata=meta))
    for name, fn in extras:
        r.register_behavior(name, lambda c, fn=fn: fn(c, r))
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))
    return r


class AdaptBasicsTests(unittest.TestCase):
    def setUp(self):
        self.extras = []

    def script(self, name, fn):
        self.extras.append((name, fn))

    def game(self, hand=(SELF,), board=(), seed=0, omitted=None):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board,
            deck=('body',) * 5, mana=10, max_mana=10), PlayerSetup('hero', hand=('body',),
            deck=('body',) * 5, mana=10, max_mana=10)), seed=seed), registry(self.extras, omitted))

    def play(self, g, cid):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid))
        return eid

    def select(self, g, cid):
        choice = g.state.pending_choice
        self.assertIn(cid, [o.id for o in choice.options])
        g.apply(SelectChoice(choice.player_id, choice.id, (cid,)))

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry(self.extras)).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.extras)).snapshot(), saved)

    def restored_select(self, g, cid):
        self.check(g)
        other = Game.from_snapshot(g.snapshot(), registry(self.extras))
        self.select(g, cid)
        self.select(other, cid)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.check(g)

    def board_cards(self, g):
        return [g.state.entities[i].card_id for i in g.state.players[1].board]

    def test_real_self_adapt_offers_exactly_three_distinct_fixed_faces_and_one_payment(self):
        g = self.game(seed=19)
        rng = random.Random()
        rng.setstate(rng_from_json(g.snapshot()['rng_state']))
        expected = rng.sample(CHOICE_IDS, 3)
        source = self.play(g, SELF)
        choice = g.state.pending_choice
        self.assertEqual([o.card_id for o in choice.options], expected)
        self.assertEqual(len(set(expected)), 3)
        self.assertEqual(rng_from_json(g.snapshot()['rng_state']), rng.getstate())
        self.assertEqual((choice.player_id, choice.source_id), (1, source))
        self.assertEqual(g.state.players[1].mana, 7)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (2, 2))
        self.restored_select(g, expected[0])
        self.assertEqual(g.state.players[1].mana, 7)
        self.assertEqual(len(g.state.play_history), 1)

    def test_all_three_numeric_results_are_real_attachments(self):
        for cid, expected in ((ATTACK, (5, 2)), (HEALTH, (2, 5)), (STATS, (3, 3))):
            with self.subTest(cid=cid):
                g = self.game(seed=seed_for(cid))
                source = self.play(g, SELF)
                self.select(g, cid)
                entity = g.state.entities[source]
                self.assertEqual((entity.attack, entity.max_health), expected)
                self.assertEqual(len(entity.enchantments), 1)
                self.assertEqual(entity.enchantments[0].source_id, source)
                self.check(g)

    def test_health_growth_preserves_existing_damage(self):
        self.script('wound', lambda c, r: [Damage(c.state.players[1].board[0], 2)])
        g = self.game(hand=('wound', GROUP), board=('body',), seed=seed_for(HEALTH))
        target = g.state.players[1].board[0]
        self.play(g, 'wound')
        self.play(g, GROUP)
        self.select(g, HEALTH)
        entity = g.state.entities[target]
        self.assertEqual((entity.max_health, entity.health, entity.damage), (8, 6, 2))
        self.check(g)

    def test_five_permanent_keyword_outcomes_install_actual_flags(self):
        for cid, keyword in (('UNG_999t6', Keyword.TAUNT), ('UNG_999t7', Keyword.WINDFURY),
                            (SHIELD, Keyword.DIVINE_SHIELD), ('UNG_999t13', Keyword.POISONOUS),
                            ('UNG_999t5', Keyword.ELUSIVE)):
            with self.subTest(cid=cid):
                g = self.game(seed=seed_for(cid))
                source = self.play(g, SELF)
                self.select(g, cid)
                self.assertIn(keyword, g.state.entities[source].keywords)
                self.assertTrue(any(a.keyword == keyword and a.origin == 'granted'
                                    for a in g.state.entities[source].abilities))
                self.check(g)

    def test_duplicate_keyword_is_still_offered_and_shields_do_not_stack(self):
        self.script('hit', lambda c, r: [Damage(c.state.players[1].board[0], 1)])
        g = self.game(hand=(GROUP, 'hit', 'hit'), board=('shielded',), seed=seed_for(SHIELD))
        target = g.state.players[1].board[0]
        self.play(g, GROUP)
        self.select(g, SHIELD)
        self.play(g, 'hit')
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[target].keywords)
        self.assertEqual(g.state.entities[target].health, 5)
        self.play(g, 'hit')
        self.assertEqual(g.state.entities[target].health, 4)
        self.check(g)

    def test_temporary_stealth_expires_at_next_actual_actor_start(self):
        g = self.game(seed=seed_for(STEALTH))
        source = self.play(g, SELF)
        self.restored_select(g, STEALTH)
        self.assertIn(Keyword.STEALTH, g.state.entities[source].keywords)
        g.apply(EndTurn(1))
        self.assertIn(Keyword.STEALTH, g.state.entities[source].keywords)
        g.apply(EndTurn(2))
        self.assertNotIn(Keyword.STEALTH, g.state.entities[source].keywords)
        self.check(g)

    def test_living_spores_summons_two_real_plants_in_the_dead_minion_slot(self):
        self.script('kill', lambda c, r: [Destroy(c.state.players[1].board[1])])
        g = self.game(hand=(GROUP, 'kill'), board=('left', 'body', 'right'), seed=seed_for(SPORES))
        self.play(g, GROUP)
        self.restored_select(g, SPORES)
        self.play(g, 'kill')
        self.assertEqual(self.board_cards(g), ['left', PLANT_ID, PLANT_ID, 'right'])
        plants = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == PLANT_ID]
        self.assertEqual(len({e.id for e in plants}), 2)
        self.assertTrue(all((e.attack, e.health, e.controller) == (1, 1, 1) for e in plants))
        self.check(g)

    def test_living_spores_uses_existing_capacity_and_keeps_only_one_plant_when_full(self):
        self.script('kill', lambda c, r: [Destroy(c.state.players[1].board[0])])
        g = self.game(hand=(GROUP, 'kill'), board=('body',) * 7, seed=seed_for(SPORES))
        self.play(g, GROUP)
        self.select(g, SPORES)
        self.play(g, 'kill')
        self.assertEqual(self.board_cards(g).count(PLANT_ID), 1)
        self.assertEqual(len(self.board_cards(g)), 7)
        self.assertTrue(any(e.kind == 'summon_failed' for e in g.events))
        self.check(g)

    def test_real_group_source_makes_one_shared_choice_for_every_selected_minion(self):
        g = self.game(hand=(GROUP,), board=('body', 'shielded', 'body'), seed=seed_for(STATS))
        original = tuple(g.state.players[1].board)
        self.play(g, GROUP)
        self.assertEqual(g.state.players[1].mana, 7)
        self.restored_select(g, STATS)
        self.assertEqual(tuple(g.state.players[1].board), original)
        self.assertTrue(all((g.state.entities[i].attack, g.state.entities[i].max_health) == (3, 6) for i in original))
        self.assertEqual(sum(e.kind == 'choice_requested' for e in g.events), 1)

    def test_empty_group_has_no_choice_and_consumes_no_rng(self):
        g = self.game(hand=(GROUP,))
        rng = g.snapshot()['rng_state']
        self.play(g, GROUP)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(g.state.players[1].mana, 7)
        self.check(g)

    def test_dormant_minions_do_not_join_the_real_group_recipe(self):
        self.script('sleep', lambda c, r: [MakeDormant(c.state.players[1].board[0], None)])
        g = self.game(hand=('sleep', GROUP), board=('body', 'body'), seed=seed_for(STATS))
        asleep, active = g.state.players[1].board
        self.play(g, 'sleep')
        self.play(g, GROUP)
        self.select(g, STATS)
        self.assertEqual((g.state.entities[asleep].attack, g.state.entities[asleep].max_health), (2, 5))
        self.assertEqual((g.state.entities[active].attack, g.state.entities[active].max_health), (3, 6))
        self.check(g)

    def test_real_double_adapt_samples_twice_and_can_choose_the_same_stat_again(self):
        g = self.game(hand=(DOUBLE,), seed=seed_for(STATS, STATS))
        rng = random.Random()
        rng.setstate(rng_from_json(g.snapshot()['rng_state']))
        first, second = rng.sample(CHOICE_IDS, 3), rng.sample(CHOICE_IDS, 3)
        source = self.play(g, DOUBLE)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options], first)
        self.restored_select(g, STATS)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options], second)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (6, 7))
        self.restored_select(g, STATS)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (7, 8))
        self.assertEqual(rng_from_json(g.snapshot()['rng_state']), rng.getstate())
        self.assertEqual(g.state.players[1].mana, 4)
        self.assertEqual(len(g.state.play_history), 1)

    def test_silence_removes_adapt_stats_and_spores_and_does_not_spawn_plants(self):
        self.script('clean', lambda c, r: [Silence(c.state.players[1].board[0]), Destroy(c.state.players[1].board[0])])
        g = self.game(hand=(DOUBLE, 'clean'), seed=seed_for(ATTACK, SPORES))
        source = self.play(g, DOUBLE)
        self.select(g, ATTACK)
        self.select(g, SPORES)
        self.assertEqual(g.state.entities[source].attack, 8)
        self.play(g, 'clean')
        self.assertEqual(g.state.entities[source].attack, 5)
        self.assertEqual(self.board_cards(g), [])
        self.check(g)

    def test_current_copy_keeps_adapt_attachments_and_base_copy_does_not(self):
        self.script('copies', lambda c, r: [CopyMinion(c.state.players[1].board[0], 1),
                                           CopyMinion(c.state.players[1].board[0], 1, mode='base')])
        g = self.game(hand=(SELF, 'copies'), seed=seed_for(STATS))
        source = self.play(g, SELF)
        self.select(g, STATS)
        self.play(g, 'copies')
        entities = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([(e.attack, e.max_health) for e in entities], [(3, 3), (3, 3), (2, 2)])
        self.assertNotEqual(entities[0].enchantments[0].id, entities[1].enchantments[0].id)
        self.assertEqual(sum(e.kind == 'choice_requested' for e in g.events), 1)
        self.check(g)

    def test_bounce_and_transform_reset_the_adapted_attachments(self):
        for action in ('bounce', 'transform'):
            with self.subTest(action=action):
                self.extras = []
                self.script(action, lambda c, r, action=action: [ReturnToHand(c.state.players[1].board[0])
                    if action == 'bounce' else Transform(c.state.players[1].board[0], 'body')])
                g = self.game(hand=(SELF, action), seed=seed_for(STATS))
                source = self.play(g, SELF)
                self.select(g, STATS)
                self.play(g, action)
                entity = g.state.entities[source]
                self.assertEqual(entity.enchantments, [])
                self.assertEqual((entity.attack, entity.max_health), (2, 2) if action == 'bounce' else (2, 5))
                self.check(g)

    def test_choice_faces_stay_private_to_the_actor_and_ordinary_state_is_observable(self):
        g = self.game(seed=seed_for(STATS))
        source = self.play(g, SELF)
        self.assertEqual(len(g.observe(1)['pending_choice']['options']), 3)
        self.assertEqual(g.observe(2)['pending_choice'], {'player_id': 1})
        enemy_json = json.dumps(g.observe(2)) + json.dumps(g.player_events(2))
        self.assertFalse(any(cid in enemy_json for cid in CHOICE_IDS))
        self.select(g, STATS)
        visible = g.observe(2)['players'][0]['board'][0]
        self.assertEqual((visible['attack'], visible['max_health']), (3, 3))
        self.assertNotIn('body', json.dumps(g.observe(1)['players'][1]['hand']))
        self.check(g)

    def test_bad_selection_rolls_back_to_the_original_choice_without_sampling_again(self):
        g = self.game(seed=seed_for(STATS))
        self.play(g, SELF)
        before = g.snapshot()
        choice = g.state.pending_choice
        with self.assertRaises(ValueError):
            g.apply(SelectChoice(1, choice.id, ('not-offered',)))
        self.assertEqual(g.snapshot(), before)
        self.restored_select(g, STATS)

    def test_failure_after_a_real_choice_rolls_back_rng_effects_and_knowledge_to_waiting(self):
        self.script('explode', lambda c, r: [RandomDamage((c.state.players[1].hero_id,
            c.state.players[2].hero_id), 1), Summon(1, 'missing')])
        self.script('broken', lambda c, r: [replace(adapt(c, tuple(c.state.players[1].board), r)[0], on_select='explode')])
        g = self.game(hand=('broken',), board=('body',), seed=seed_for(STATS))
        self.play(g, 'broken')
        self.check(g)
        before = g.snapshot()
        with self.assertRaisesRegex(ValueError, 'unsupported card'):
            self.select(g, STATS)
        self.assertEqual(g.snapshot(), before)

    def test_missing_outcome_or_plant_errors_before_sampling_and_does_not_shrink_the_pool(self):
        for omitted in ('UNG_999t5', PLANT_ID):
            with self.subTest(omitted=omitted):
                g = self.game(omitted=omitted)
                before = g.snapshot()
                with self.assertRaisesRegex(ValueError, 'unsupported card'):
                    self.play(g, SELF)
                self.assertEqual(g.snapshot(), before)

    def test_factory_rejects_bad_target_declarations_and_is_pure_for_empty_non_board_targets(self):
        g = self.game(board=('body',))
        source = g.state.players[1].board[0]
        ctx = RuleContext(g.state, source, 1)
        for targets in ([source], (source, source), (True,), (-1,), (99999,)):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                adapt(ctx, targets, g.registry)
        before = g.snapshot()
        self.assertEqual(adapt(ctx, (), g.registry), ())
        self.assertEqual(adapt(ctx, tuple(g.state.players[1].hand), g.registry), ())
        self.assertEqual(g.snapshot(), before)

    def test_only_choice_faces_and_the_real_plant_are_installed_by_the_recipe_library(self):
        r = Registry('adapt-install-check-' + VERSION)
        register_adapt_options(r)
        self.assertEqual(set(r.cards), set(CHOICE_IDS) | {PLANT_ID})
        self.assertTrue(all(r.card(cid).choice_only for cid in CHOICE_IDS))
        self.assertTrue(all(not r.card(cid).hand_playable for cid in CHOICE_IDS))
        self.assertFalse(r.card(PLANT_ID).metadata.collectible)
        self.assertEqual((r.card(PLANT_ID).cost, r.card(PLANT_ID).attack, r.card(PLANT_ID).health), (1, 1, 1))
        self.assertIsNotNone(r.behavior(SPORES_BEHAVIOR))


if __name__ == '__main__':
    unittest.main()
